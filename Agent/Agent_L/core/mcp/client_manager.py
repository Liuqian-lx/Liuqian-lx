"""MCP 客户端连接管理。

职责：
- 为 .mcp.json 中的每个服务器建立会话（stdio / streamable_http）
- 连接成功后调用标准 list_tools()，记录每个工具的原始名称、描述与 inputSchema
- 维护「对外暴露的工具名 → (服务器, 原始工具名)」路由表
- 提供线程安全 call_tool()，供同步的工具函数直接调用
- 单服务器失败只跳过该服务器，不影响其他服务器与本地工具

实现要点：
MCP 的 async 上下文（传输层 + ClientSession）必须在同一个 asyncio 任务中
进入和退出，因此每个服务器都有独立的常驻协程 _serve()，所有请求通过
asyncio 队列投递，由该协程串行执行并在调用结束后回填 concurrent.futures.Future。
主线程通过 run_coroutine_threadsafe / queue 与后台事件循环交互。
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import concurrent.futures.thread  # noqa: F401 - 提前注册线程池关闭钩子，见 _register_shutdown_hook
import logging
import os
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .config import (
    MCPServerConfig,
    MCPConfigLoadResult,
    PROTOCOL_STDIO,
    load_mcp_config,
)

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_CALL_TIMEOUT = 60.0
DISABLE_ENV_VAR = "AGENT_L_DISABLE_MCP"
_TRUTHY = {"1", "true", "yes", "on"}

try:  # Python 3.11+
    _EXCEPTION_GROUP_TYPES: tuple = (BaseExceptionGroup,)
except NameError:  # pragma: no cover - 兼容旧解释器
    _EXCEPTION_GROUP_TYPES = ()

try:  # MCP SDK 属于可选依赖：缺失时 Agent 退化为纯本地工具模式
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    try:
        from mcp.client.streamable_http import (
            streamable_http_client as _streamable_http_client,
        )
    except ImportError:  # mcp < 2.0 的命名
        from mcp.client.streamable_http import (
            streamablehttp_client as _streamable_http_client,
        )

    try:
        from mcp.client.streamable_http import create_mcp_http_client
    except ImportError:  # 旧版本没有该辅助函数
        create_mcp_http_client = None  # type: ignore[assignment]

    MCP_AVAILABLE = True
    MCP_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - 取决于运行环境
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    _streamable_http_client = None  # type: ignore[assignment]
    create_mcp_http_client = None  # type: ignore[assignment]
    MCP_AVAILABLE = False
    MCP_IMPORT_ERROR = str(exc)


class MCPError(Exception):
    """MCP 连接或调用失败。"""


@dataclass(frozen=True)
class ToolRoute:
    """一个对外暴露的 MCP 工具及其路由目标。"""

    exposed_name: str
    server_name: str
    original_name: str
    tool: Any


@dataclass
class _Connection:
    """单个服务器的运行时状态。"""

    name: str
    config: MCPServerConfig
    queue: Optional["asyncio.Queue[Any]"] = None
    tools: List[Any] = field(default_factory=list)
    ready: bool = False
    error: Optional[str] = None
    init_future: Optional[concurrent.futures.Future] = None
    serve_future: Optional[concurrent.futures.Future] = None


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """兼容 snake_case / camelCase 两种字段命名。"""
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _describe_error(exc: BaseException) -> str:
    """把 anyio / asyncio 的 ExceptionGroup 展开成可读的一行错误。"""
    if _EXCEPTION_GROUP_TYPES and isinstance(exc, _EXCEPTION_GROUP_TYPES):
        messages: List[str] = []
        for inner in exc.exceptions:
            text = _describe_error(inner)
            if text and text not in messages:
                messages.append(text)
        if messages:
            return "；".join(messages)
        return exc.__class__.__name__

    text = str(exc).strip()
    if text:
        return text
    return exc.__class__.__name__


def _sanitize_identifier(text: str, fallback: str = "tool") -> str:
    """把任意名称转换为合法的函数名片段（ASCII 字母 / 数字 / 下划线 / 连字符）。"""
    cleaned = "".join(
        char
        if ((char.isascii() and char.isalnum()) or char in "_-")
        else "_"
        for char in text
    ).strip("_")
    if not cleaned:
        cleaned = fallback
    return cleaned[:64]


def _unique_name(candidate: str, used: Set[str]) -> str:
    if candidate not in used:
        return candidate
    base = candidate[:60]
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


class MCPClientManager:
    """管理所有 MCP 服务器连接与工具路由。"""

    def __init__(
        self,
        load_result: Optional[MCPConfigLoadResult] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
    ):
        self._load_result = load_result or MCPConfigLoadResult()
        self._connect_timeout = max(0.1, float(connect_timeout))
        self._call_timeout = max(0.1, float(call_timeout))

        self._connections: Dict[str, _Connection] = {}
        self._routes: Dict[str, ToolRoute] = {}
        self._reserved_names: Set[str] = set()
        self._errors: List[str] = list(self._load_result.errors)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._serve_futures: List[concurrent.futures.Future] = []
        self._start_lock = threading.Lock()
        self._started = False
        self._closed = False

    # ------------------------------------------------------------------ 生命周期
    def start(self, reserved_names: Optional[Iterable[str]] = None) -> "MCPClientManager":
        """建立所有连接并生成工具路由；重复调用不会重复连接。"""
        with self._start_lock:
            if self._started:
                if reserved_names is not None:
                    self._reserved_names = set(reserved_names)
                    self._rebuild_routes()
                return self
            self._started = True
            if reserved_names is not None:
                self._reserved_names = set(reserved_names)

        if not MCP_AVAILABLE:
            self._record_error(f"MCP SDK 不可用：{MCP_IMPORT_ERROR}")
            return self
        if not self._load_result.servers:
            return self

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="agent-l-mcp", daemon=True
        )
        self._thread.start()

        pending: List[Tuple[_Connection, concurrent.futures.Future]] = []
        for config in self._load_result.servers:
            conn = _Connection(name=config.name, config=config)
            conn.init_future = concurrent.futures.Future()
            self._connections[config.name] = conn
            assert self._loop is not None
            conn.serve_future = asyncio.run_coroutine_threadsafe(
                self._serve(conn), self._loop
            )
            self._serve_futures.append(conn.serve_future)
            pending.append((conn, conn.init_future))

        deadline = time.monotonic() + self._connect_timeout
        for conn, future in pending:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                future.result(timeout=remaining)
            except concurrent.futures.TimeoutError:
                conn.error = f"连接超时（超过 {self._connect_timeout:g} 秒）"
                if conn.serve_future is not None:
                    conn.serve_future.cancel()
            except Exception as exc:  # _serve 理论上不会抛，兜底
                conn.error = _describe_error(exc)

        self._rebuild_routes()
        return self

    def close(self, wait: float = 3.0) -> None:
        """关闭所有连接并停止后台事件循环（供 atexit 调用）。"""
        with self._start_lock:
            if self._closed:
                return
            self._closed = True

        loop = self._loop
        if loop is None:
            return

        def _wake_all() -> None:
            for conn in self._connections.values():
                if conn.queue is not None:
                    try:
                        conn.queue.put_nowait(None)
                    except Exception:
                        pass

        try:
            loop.call_soon_threadsafe(_wake_all)
        except RuntimeError:
            pass

        try:
            concurrent.futures.wait(self._serve_futures, timeout=wait)
        except Exception:
            pass

        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=wait)

    @property
    def errors(self) -> List[str]:
        """连接与配置阶段的错误信息（供界面或日志展示）。"""
        return list(self._errors)

    # ------------------------------------------------------------------ 工具
    def list_routes(self) -> List[ToolRoute]:
        """返回当前已暴露的 MCP 工具路由（按名称排序，便于稳定展示）。"""
        return [self._routes[name] for name in sorted(self._routes)]

    def get_route(self, exposed_name: str) -> Optional[ToolRoute]:
        return self._routes.get(exposed_name)

    def call_server_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """把一次 call_tool 投递到对应服务器并同步等待结果；失败抛 MCPError。"""
        conn = self._connections.get(server_name)
        if conn is None:
            raise MCPError(f"MCP 服务器「{server_name}」未配置")
        if not conn.ready or conn.queue is None:
            reason = conn.error or "尚未连接成功"
            raise MCPError(f"MCP 服务器「{server_name}」不可用：{reason}")

        loop = self._loop
        if loop is None or loop.is_closed() or self._closed:
            raise MCPError("MCP 客户端已关闭，无法调用工具")

        future: concurrent.futures.Future = concurrent.futures.Future()
        item = (future, tool_name, dict(arguments or {}))
        try:
            loop.call_soon_threadsafe(conn.queue.put_nowait, item)
        except RuntimeError as exc:
            raise MCPError(f"MCP 服务器「{server_name}」连接已关闭：{exc}") from exc

        try:
            return future.result(timeout=self._call_timeout + 5.0)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise MCPError(
                f"调用 MCP 工具「{tool_name}」超时（超过 {self._call_timeout:g} 秒）"
            ) from exc
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError(f"调用 MCP 工具「{tool_name}」失败：{exc}") from exc

    # ------------------------------------------------------------------ 内部
    def _run_loop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _serve(self, conn: _Connection) -> None:
        """单个服务器的常驻协程：建立会话 → 常驻派发调用 → 清理。"""
        assert ClientSession is not None
        queue: "asyncio.Queue[Any]" = asyncio.Queue()
        conn.queue = queue
        try:
            async with self._open_session(conn.config) as session:
                try:
                    await asyncio.wait_for(
                        session.initialize(), timeout=self._connect_timeout
                    )
                    tools_result = await asyncio.wait_for(
                        session.list_tools(), timeout=self._connect_timeout
                    )
                except asyncio.TimeoutError as exc:
                    raise MCPError(
                        f"初始化超时（超过 {self._connect_timeout:g} 秒）"
                    ) from exc

                conn.tools = list(_attr(tools_result, "tools", default=[]) or [])
                conn.ready = True
                conn.error = None
                self._set_init_result(conn, None)
                await self._dispatch(conn, session, queue)
        except asyncio.CancelledError:
            conn.error = conn.error or "连接已取消"
            self._set_init_result(conn, conn.error)
            raise
        except Exception as exc:
            conn.error = _describe_error(exc)
            self._set_init_result(conn, conn.error)
            logger.debug("MCP 服务器 %s 连接失败：%s", conn.name, conn.error)
        finally:
            conn.ready = False
            self._fail_pending(conn, f"MCP 服务器「{conn.name}」连接已关闭")

    async def _dispatch(self, conn: _Connection, session: Any, queue: Any) -> None:
        """串行处理队列中的 call_tool 请求，直到收到关闭信号。"""
        while True:
            item = await queue.get()
            if item is None:
                return
            future, tool_name, arguments = item
            if future.done():  # 调用方已超时放弃
                continue
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=self._call_timeout,
                )
                if not future.done():
                    future.set_result(result)
            except asyncio.TimeoutError:
                if not future.done():
                    future.set_exception(
                        MCPError(
                            f"调用 MCP 工具「{tool_name}」超时"
                            f"（超过 {self._call_timeout:g} 秒）"
                        )
                    )
            except Exception as exc:
                if not future.done():
                    future.set_exception(
                        MCPError(f"调用 MCP 工具「{tool_name}」失败：{_describe_error(exc)}")
                    )

    @asynccontextmanager
    async def _open_session(self, config: MCPServerConfig):
        """按协议打开传输层与 ClientSession（同一任务内进入/退出）。"""
        assert ClientSession is not None

        if config.type == PROTOCOL_STDIO:
            assert stdio_client is not None and StdioServerParameters is not None
            params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
                env=dict(config.env) or None,
                cwd=config.cwd or None,
            )
            async with stdio_client(params) as streams:
                read_stream, write_stream = self._split_streams(streams)
                async with ClientSession(read_stream, write_stream) as session:
                    yield session
            return

        assert _streamable_http_client is not None
        if config.headers and create_mcp_http_client is not None:
            async with create_mcp_http_client(headers=dict(config.headers)) as client:
                async with _streamable_http_client(
                    config.url, http_client=client
                ) as streams:
                    read_stream, write_stream = self._split_streams(streams)
                    async with ClientSession(read_stream, write_stream) as session:
                        yield session
            return

        async with _streamable_http_client(config.url) as streams:
            read_stream, write_stream = self._split_streams(streams)
            async with ClientSession(read_stream, write_stream) as session:
                yield session

    @staticmethod
    def _split_streams(streams: Any) -> Tuple[Any, Any]:
        """兼容新版 (read, write) 与旧版 (read, write, get_session_id)。"""
        if isinstance(streams, (tuple, list)) and len(streams) >= 2:
            return streams[0], streams[1]
        raise MCPError("MCP 传输层返回了无法识别的数据流")

    def _set_init_result(self, conn: _Connection, error: Optional[str]) -> None:
        future = conn.init_future
        if future is None or future.done():
            return
        try:
            future.set_result(error)
        except Exception:  # pragma: no cover - 并发下的极小概率
            pass

    def _fail_pending(self, conn: _Connection, message: str) -> None:
        queue = conn.queue
        if queue is None:
            return
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            except Exception:
                return
            if item is None:
                continue
            future = item[0]
            if not future.done():
                try:
                    future.set_exception(MCPError(message))
                except Exception:
                    pass

    def _rebuild_routes(self) -> None:
        """根据所有已连接服务器的工具列表生成对外工具名与路由。"""
        name_counts: Counter = Counter()
        for conn in self._connections.values():
            if not conn.ready:
                continue
            for tool in conn.tools:
                original = _attr(tool, "name", default="")
                if isinstance(original, str) and original:
                    name_counts[original] += 1

        used: Set[str] = set(self._reserved_names)
        routes: Dict[str, ToolRoute] = {}
        for server_name in sorted(self._connections):
            conn = self._connections[server_name]
            if not conn.ready:
                if conn.error:
                    target = (
                        conn.config.url or conn.config.command or conn.config.type
                    )
                    self._record_error(
                        f"MCP 服务器「{conn.name}」（{target}）连接失败：{conn.error}"
                    )
                continue
            for tool in conn.tools:
                original = _attr(tool, "name", default="")
                if not isinstance(original, str) or not original.strip():
                    continue
                original = original.strip()

                # 不同服务器出现同名工具，或与本地工具同名时，加服务器名前缀
                if name_counts[original] > 1 or original in self._reserved_names:
                    prefix = _sanitize_identifier(server_name, "server")
                    exposed = f"{prefix}_{_sanitize_identifier(original)}"
                else:
                    exposed = _sanitize_identifier(original)
                exposed = _unique_name(exposed, used)

                used.add(exposed)
                routes[exposed] = ToolRoute(
                    exposed_name=exposed,
                    server_name=server_name,
                    original_name=original,
                    tool=tool,
                )

        self._routes = routes

    def _record_error(self, message: str) -> None:
        if message not in self._errors:
            self._errors.append(message)


_mcp_manager: Optional[MCPClientManager] = None
_manager_lock = threading.Lock()


def mcp_disabled() -> bool:
    """环境变量 AGENT_L_DISABLE_MCP 为真时完全禁用 MCP（离线脚本/排障用）。"""
    return os.environ.get(DISABLE_ENV_VAR, "").strip().lower() in _TRUTHY


def get_mcp_manager(
    load_result: Optional[MCPConfigLoadResult] = None,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    call_timeout: float = DEFAULT_CALL_TIMEOUT,
) -> MCPClientManager:
    """返回进程内唯一的 MCP 管理器（读取一次 .mcp.json）。"""
    global _mcp_manager
    with _manager_lock:
        if _mcp_manager is None:
            if load_result is None:
                load_result = (
                    MCPConfigLoadResult() if mcp_disabled() else load_mcp_config()
                )
            _mcp_manager = MCPClientManager(
                load_result,
                connect_timeout=connect_timeout,
                call_timeout=call_timeout,
            )
        return _mcp_manager


def reset_mcp_manager() -> None:
    """关闭并丢弃当前单例（主要用于测试或重新加载配置）。"""
    global _mcp_manager
    with _manager_lock:
        manager = _mcp_manager
        _mcp_manager = None
    if manager is not None:
        manager.close()


def _shutdown_at_exit() -> None:
    manager = _mcp_manager
    if manager is not None:
        try:
            manager.close(wait=2.0)
        except Exception:
            pass


def _register_shutdown_hook() -> None:
    """在解释器关闭线程池之前完成 MCP 会话清理。

    concurrent.futures.thread 会通过 threading._register_atexit 注册线程池关闭
    钩子，且普通 atexit 回调会在它之后执行；一旦线程池先关闭，MCP 关闭会话时
    的 HTTP 请求就无处调度。这里先确保该模块已被导入（其钩子已注册），再用同一
    机制注册清理函数，保证「后注册者先执行」，让 MCP 清理赶在线程池关闭之前。
    """
    register = getattr(threading, "_register_atexit", None)
    if register is not None:
        try:
            register(_shutdown_at_exit)
            return
        except Exception:
            pass
    atexit.register(_shutdown_at_exit)


_register_shutdown_hook()
