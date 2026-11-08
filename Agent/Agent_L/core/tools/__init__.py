"""工具注册与执行入口。

对外提供：
- TOOLS：合并后的工具 schema 列表
  （2 个内置工具 + 10 个文件工具 + 1 个联网搜索工具 + 1 个网页正文提取工具
   + 1 个命令行执行工具 + 1 个技能加载工具 + 1 个技能创建工具
   + 1 个 MCP 配置管理工具 + 1 个上下文检索工具
   + 由 .mcp.json 动态发现的 MCP 工具）
- TOOL_MAP：工具名 -> 可调用函数
- execute_tool(name, arguments)：统一解析参数、执行工具、捕获异常
- refresh_mcp_tools()：重新读取 .mcp.json 并热重载 MCP 工具（供 createMCP 调用）

MCP 工具与本地工具共享同一套 TOOLS / TOOL_MAP 契约：
- 连接失败、配置缺失或 SDK 不可用时 MCP 部分为空，不影响本地工具；
- MCP 工具的结果同样由 execute_tool 统一捕获异常并返回标准字典。
"""

from __future__ import annotations

import gc
import json
from typing import Any, Dict, List, Optional, Tuple

from ..mcp import init_mcp_tools
from .builtin import TOOLS as BUILTIN_TOOLS
from .builtin import TOOL_MAP as BUILTIN_TOOL_MAP
from .create_mcp import TOOLS as CREATE_MCP_TOOLS
from .create_mcp import TOOL_MAP as CREATE_MCP_TOOL_MAP
from .create_skill import TOOLS as CREATE_SKILL_TOOLS
from .create_skill import TOOL_MAP as CREATE_SKILL_TOOL_MAP
from .file_ops import TOOLS as FILE_TOOLS
from .file_ops import TOOL_MAP as FILE_TOOL_MAP
from .recall_context import TOOLS as RECALL_CONTEXT_TOOLS
from .recall_context import TOOL_MAP as RECALL_CONTEXT_TOOL_MAP
from .run_cli import TOOLS as RUN_CLI_TOOLS
from .run_cli import TOOL_MAP as RUN_CLI_TOOL_MAP
from .skill_loader import TOOLS as SKILL_TOOLS
from .skill_loader import TOOL_MAP as SKILL_TOOL_MAP
from .web_fetch import TOOLS as WEB_FETCH_TOOLS
from .web_fetch import TOOL_MAP as WEB_FETCH_TOOL_MAP
from .web_search import TOOLS as WEB_SEARCH_TOOLS
from .web_search import TOOL_MAP as WEB_SEARCH_TOOL_MAP

LOCAL_TOOLS = (
    BUILTIN_TOOLS
    + FILE_TOOLS
    + WEB_SEARCH_TOOLS
    + WEB_FETCH_TOOLS
    + RUN_CLI_TOOLS
    + SKILL_TOOLS
    + CREATE_SKILL_TOOLS
    + CREATE_MCP_TOOLS
    + RECALL_CONTEXT_TOOLS
)
LOCAL_TOOL_MAP = {
    **BUILTIN_TOOL_MAP,
    **FILE_TOOL_MAP,
    **WEB_SEARCH_TOOL_MAP,
    **WEB_FETCH_TOOL_MAP,
    **RUN_CLI_TOOL_MAP,
    **SKILL_TOOL_MAP,
    **CREATE_SKILL_TOOL_MAP,
    **CREATE_MCP_TOOL_MAP,
    **RECALL_CONTEXT_TOOL_MAP,
}

# 会话初始化阶段（core.tools 被导入时）连接 .mcp.json 中的全部服务器。
# 本地工具名作为保留名传入，MCP 同名工具会自动加服务器名前缀，避免覆盖。
MCP_TOOLS, MCP_TOOL_MAP = init_mcp_tools(set(LOCAL_TOOL_MAP))

TOOLS = LOCAL_TOOLS + MCP_TOOLS
TOOL_MAP = {**LOCAL_TOOL_MAP, **MCP_TOOL_MAP}

__all__ = [
    "TOOLS",
    "TOOL_MAP",
    "LOCAL_TOOLS",
    "LOCAL_TOOL_MAP",
    "MCP_TOOLS",
    "MCP_TOOL_MAP",
    "execute_tool",
    "refresh_mcp_tools",
    "tool_result_content",
]


def refresh_mcp_tools() -> Tuple[List[Dict[str, Any]], List[str]]:
    """重新读取 .mcp.json，刷新 MCP 工具路由与工具列表。

    供 createMCP 在写入配置后调用：先关闭旧连接，再按最新配置重新连接、
    发现工具，并原地更新本模块的 TOOLS / TOOL_MAP，使未重启的会话也能
    在下一轮模型请求中使用新工具。

    返回 (MCP 工具 schema 列表, 管理器错误信息列表)；不抛异常。
    """
    global MCP_TOOLS, MCP_TOOL_MAP

    try:
        from ..mcp import build_mcp_tools, get_mcp_manager, reset_mcp_manager

        reset_mcp_manager()
        manager = get_mcp_manager()
        manager.start(set(LOCAL_TOOL_MAP))

        new_tools, new_map = build_mcp_tools(manager)
        MCP_TOOLS = new_tools
        MCP_TOOL_MAP = new_map

        combined_tools = LOCAL_TOOLS + MCP_TOOLS
        TOOLS[:] = combined_tools
        TOOL_MAP.clear()
        TOOL_MAP.update({**LOCAL_TOOL_MAP, **MCP_TOOL_MAP})

        _refresh_live_sessions(combined_tools)
        return MCP_TOOLS, manager.errors
    except Exception as exc:  # 热重载失败不应破坏已有工具表
        return MCP_TOOLS, [f"刷新 MCP 工具失败：{exc}"]


def _refresh_live_sessions(tools: List[Dict[str, Any]]) -> None:
    """让已创建的 ChatSession 同步最新工具列表。

    ChatSession 初始化时会复制一份 TOOLS；为遵守「不修改 session.py」的约束，
    这里通过 GC 找到存活的会话对象，原地更新其 ``_tools`` 列表。
    """
    try:
        objects = gc.get_objects()
    except Exception:
        return

    for obj in objects:
        try:
            if type(obj).__name__ != "ChatSession":
                continue
            current = getattr(obj, "_tools", None)
            if isinstance(current, list):
                current[:] = tools
        except Exception:
            continue


def execute_tool(name: str, arguments: Optional[str]) -> Dict[str, Any]:
    """执行指定工具并返回统一格式的结果字典。

    参数 arguments 是大模型给出的 JSON 字符串；解析或执行失败时不会抛异常，
    而是返回 {"success": False, "error": ...}，保证会话流程不中断。
    """
    func = TOOL_MAP.get(name)
    if func is None:
        return {"success": False, "error": f"未知工具：{name}"}

    try:
        raw = (arguments or "").strip()
        args = json.loads(raw) if raw else {}
        if not isinstance(args, dict):
            return {"success": False, "error": "工具参数必须是 JSON 对象"}

        result = func(**args)
        if not isinstance(result, dict):
            result = {"success": True, "result": result}
        result.setdefault("success", True)
        return result
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"工具参数解析失败：{exc}"}
    except Exception as exc:
        return {"success": False, "error": f"工具调用失败：{exc}"}


def tool_result_content(result: Dict[str, Any]) -> str:
    """把工具结果序列化为发送给大模型的文本。"""
    return json.dumps(result, ensure_ascii=False)
