"""MCP 客户端模块。

对外提供：
- load_mcp_config / load_mcp_server_configs：读取 .mcp.json
- get_mcp_manager / reset_mcp_manager：进程内 MCP 连接管理器
- init_mcp_tools：建立连接并返回 (TOOLS, TOOL_MAP) 形式的动态工具
- build_mcp_tools / call_mcp_tool：工具适配与调用转发

所有 MCP 能力都是可选的：配置缺失、SDK 缺失或服务器不可用时，
Agent 会静默退化为纯本地工具模式。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .client_manager import (
    MCP_AVAILABLE,
    MCP_IMPORT_ERROR,
    MCPClientManager,
    MCPError,
    ToolRoute,
    get_mcp_manager,
    mcp_disabled,
    reset_mcp_manager,
)
from .config import (
    MCPServerConfig,
    MCPConfigLoadResult,
    load_mcp_config,
    load_mcp_server_configs,
)
from .tool_adapter import (
    build_mcp_tools,
    call_mcp_tool,
    input_schema_to_parameters,
    normalize_tool_result,
    tool_route_to_schema,
)

__all__ = [
    "MCP_AVAILABLE",
    "MCP_IMPORT_ERROR",
    "MCPClientManager",
    "MCPConfigLoadResult",
    "MCPError",
    "MCPServerConfig",
    "ToolRoute",
    "build_mcp_tools",
    "call_mcp_tool",
    "get_mcp_manager",
    "init_mcp_tools",
    "input_schema_to_parameters",
    "load_mcp_config",
    "load_mcp_server_configs",
    "mcp_disabled",
    "normalize_tool_result",
    "reset_mcp_manager",
    "tool_route_to_schema",
]


def init_mcp_tools(
    reserved_names: Optional[Iterable[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Callable[..., Dict[str, Any]]]]:
    """初始化 MCP 客户端并返回可直接合并进工具体系的 (TOOLS, TOOL_MAP)。

    reserved_names 为本地已占用的工具名：MCP 工具若重名会自动加服务器名前缀。
    任何失败都不会抛异常，只会得到空列表。
    """
    try:
        manager = get_mcp_manager()
        manager.start(reserved_names)
        return build_mcp_tools(manager)
    except Exception:
        return [], {}
