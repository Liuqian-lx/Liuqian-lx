"""宠物医院 MCP 服务入口。

默认以 Streamable HTTP 模式运行，监听 0.0.0.0:8090，MCP 端点为 /mcp，
可直接被 Agent_L 等标准 MCP 客户端通过 .mcp.json 接入。

用法：
    python main.py                      # 默认 HTTP 模式（0.0.0.0:8090）
    python main.py --http --port 8090   # 显式指定 HTTP 参数
    python main.py --stdio              # stdio 模式（供只支持 stdio 的客户端）
    MCP_TRANSPORT=stdio python main.py  # 通过环境变量切换

注意：stdio 模式下 stdout 是协议通道，所有日志一律写到 stderr。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys

from mcp.server import MCPServer
from mcp.server.caching import CacheHint

from internal.tools import register_tools

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8090
DEFAULT_PATH = "/mcp"

_HTTP_TRANSPORT_ALIASES = {"http", "streamable_http", "streamable-http", "streamablehttp"}


def create_server() -> MCPServer:
    server = MCPServer(
        name="pet-hospital",
        version="1.0.0",
        description="宠物医院管理系统 MCP 服务",
        cache_hints={
            "tools/list": CacheHint(ttl_ms=60000, scope="private"),
        },
    )
    register_tools(server)
    return server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="宠物医院 MCP 服务")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--http", action="store_true", help="以 Streamable HTTP 模式运行（默认）")
    mode.add_argument("--stdio", action="store_true", help="以 stdio 模式运行")
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", DEFAULT_HOST),
        help=f"HTTP 监听地址（默认 {DEFAULT_HOST}）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", str(DEFAULT_PORT))),
        help=f"HTTP 监听端口（默认 {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--path",
        default=os.getenv("MCP_PATH", DEFAULT_PATH),
        help=f"MCP 端点路径（默认 {DEFAULT_PATH}）",
    )
    return parser


def _resolve_transport(args: argparse.Namespace) -> str:
    """确定传输模式：命令行 > 环境变量 > 默认 HTTP。"""
    if args.stdio:
        return "stdio"
    if args.http:
        return "streamable-http"

    env_value = os.getenv("MCP_TRANSPORT", "").strip().lower()
    if env_value == "stdio":
        return "stdio"
    if env_value in _HTTP_TRANSPORT_ALIASES:
        return "streamable-http"
    return "streamable-http"


def _port_available(host: str, port: int) -> bool:
    """启动前检查端口是否空闲，用于给出明确的冲突提示。

    Windows 上已有进程监听 0.0.0.0:port 时，另一个 socket 仍可成功
    bind 到 127.0.0.1:port（未启用 SO_EXCLUSIVEADDRUSE），因此这里改用
    连接探测：能连上说明端口已被占用。
    """
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            if sock.connect_ex((probe_host, port)) == 0:
                return False
        except OSError:
            pass
    return True


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    transport = _resolve_transport(args)
    server = create_server()

    if transport == "stdio":
        # stdout 被协议占用，只向 stderr 输出日志
        _log("[MCP] 传输模式：stdio（stdin/stdout JSON-RPC）")
        _log("[MCP] 已就绪，等待客户端通过 stdio 连接……")
        try:
            server.run("stdio")
        except KeyboardInterrupt:
            _log("[MCP] 收到中断信号，服务已退出")
        except Exception as exc:  # pragma: no cover - 运行时异常兜底
            _log(f"[MCP] 服务异常退出：{exc}")
            return 1
        return 0

    if not _port_available(args.host, args.port):
        _log(
            f"[MCP] 启动失败：端口 {args.port} 已被占用"
            f"（可能是浏览器中的 Pet Hospital REST 服务或其他 MCP 服务）。"
        )
        _log(f"[MCP] 请释放端口，或用 --port 指定其他端口。")
        return 1

    endpoint_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    _log("[MCP] ==========================================")
    _log("[MCP] 宠物医院 MCP 服务启动成功")
    _log(f"[MCP] 传输模式：streamable-http")
    _log(f"[MCP] 监听地址：{args.host}:{args.port}")
    _log(f"[MCP] MCP 端点：http://{endpoint_host}:{args.port}{args.path}")
    _log(f"[MCP] 工具：list_pets / create_pet")
    _log("[MCP] 按 Ctrl+C 停止服务")
    _log("[MCP] ==========================================")

    try:
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
        )
    except KeyboardInterrupt:
        _log("[MCP] 收到中断信号，服务已退出")
        return 0
    except OSError as exc:
        _log(f"[MCP] 启动失败：无法监听 {args.host}:{args.port}：{exc}")
        return 1
    except SystemExit as exc:  # uvicorn 启动失败时可能抛出
        code = exc.code if isinstance(exc.code, int) else 1
        if code != 0:
            _log(f"[MCP] 服务异常退出（退出码 {code}），请检查上方日志")
        return code
    except Exception as exc:  # pragma: no cover - 运行时异常兜底
        _log(f"[MCP] 服务异常退出：{exc}")
        return 1

    _log("[MCP] 服务已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
