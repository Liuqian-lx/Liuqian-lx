"""MCP 工具适配层。

- 把 MCP 的 inputSchema 转换成与本地工具风格一致的 OpenAI Function Call Schema
- 生成可被 TOOL_MAP 直接使用的同步工具函数
- 把 MCP 的 CallToolResult（文本 / 结构化数据 / 错误）统一包装为
  {"success": True, "result": ...} 或 {"success": False, "error": ...}

本模块所有对外函数都不向调用方抛异常。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .client_manager import MCPClientManager, ToolRoute

_EMPTY_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

# 需要保留的 JSON Schema 关键字（其余字段对函数调用无意义，丢弃以贴合本地工具风格）
_PRESERVED_SCHEMA_KEYS = (
    "additionalProperties",
    "definitions",
    "$defs",
    "anyOf",
    "oneOf",
    "allOf",
)


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """兼容 MCP SDK 各版本的蛇形 / 驼峰字段命名。"""
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def input_schema_to_parameters(schema: Any) -> Dict[str, Any]:
    """把 MCP inputSchema 归一化为 OpenAI 函数参数 Schema。"""
    if not isinstance(schema, Mapping):
        return dict(_EMPTY_PARAMETERS)

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}

    required = schema.get("required")
    if isinstance(required, (list, tuple)):
        required_keys = [item for item in required if isinstance(item, str)]
    else:
        required_keys = []

    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "required": required_keys,
    }
    for key in _PRESERVED_SCHEMA_KEYS:
        if key in schema:
            parameters[key] = schema[key]
    return parameters


def tool_route_to_schema(route: ToolRoute) -> Dict[str, Any]:
    """把一个 MCP 工具路由转换为 OpenAI Function Call Schema。"""
    tool = route.tool
    name = _attr(tool, "name", default=route.original_name) or route.original_name
    description = _attr(tool, "description", default="") or f"MCP 工具：{name}"
    schema = _attr(tool, "inputSchema", "input_schema", default=None)
    if schema is None and isinstance(tool, Mapping):
        schema = tool.get("inputSchema") or tool.get("input_schema")
    return {
        "type": "function",
        "function": {
            "name": route.exposed_name,
            "description": str(description),
            "parameters": input_schema_to_parameters(schema),
        },
    }


def build_mcp_tools(
    manager: MCPClientManager,
) -> Tuple[List[Dict[str, Any]], Dict[str, Callable[..., Dict[str, Any]]]]:
    """返回 (TOOLS schema 列表, TOOL_MAP 名称映射)。"""
    tools: List[Dict[str, Any]] = []
    tool_map: Dict[str, Callable[..., Dict[str, Any]]] = {}

    for route in manager.list_routes():
        tools.append(tool_route_to_schema(route))
        tool_map[route.exposed_name] = make_mcp_tool_function(manager, route)
    return tools, tool_map


def make_mcp_tool_function(
    manager: MCPClientManager,
    route: ToolRoute,
) -> Callable[..., Dict[str, Any]]:
    """生成一个与本地工具签名一致的同步函数（kwargs 即工具参数）。"""

    def _invoke(**arguments: Any) -> Dict[str, Any]:
        return call_mcp_tool(manager, route.exposed_name, arguments)

    _invoke.__name__ = route.exposed_name
    _invoke.__doc__ = f"调用 MCP 服务器「{route.server_name}」的工具 {route.original_name}。"
    return _invoke


def call_mcp_tool(
    manager: MCPClientManager,
    exposed_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按对外工具名路由到对应 MCP 服务器并执行 call_tool。

    永远返回统一格式字典，不向调用方抛异常。
    """
    try:
        route = manager.get_route(exposed_name)
        if route is None:
            return {"success": False, "error": f"未知的 MCP 工具：{exposed_name}"}

        if arguments is not None and not isinstance(arguments, Mapping):
            return {"success": False, "error": "MCP 工具参数必须是对象"}

        raw = manager.call_server_tool(
            route.server_name,
            route.original_name,
            dict(arguments or {}),
        )
        return normalize_tool_result(raw)
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        return {"success": False, "error": detail}


def normalize_tool_result(raw: Any) -> Dict[str, Any]:
    """把 MCP CallToolResult 包装为统一结果格式。

    - is_error / isError 为真 → {"success": False, "error": ...}
    - 文本内容 → result 为拼接后的字符串
    - 结构化数据（structuredContent）→ 优先保留在 result 中
    - 两者都有 → result = {"text": ..., "structuredContent": ...}
    """
    if raw is None:
        return {"success": True, "result": ""}

    if isinstance(raw, dict):
        return {"success": True, "result": raw}

    is_error = bool(_attr(raw, "isError", "is_error", default=False))
    blocks = _attr(raw, "content", default=None)
    structured = _attr(
        raw, "structuredContent", "structured_content", default=None
    )

    texts: List[str] = []
    if isinstance(blocks, (list, tuple)):
        for block in blocks:
            text = _block_to_text(block)
            if text:
                texts.append(text)
    elif blocks is not None:
        text = _block_to_text(blocks)
        if text:
            texts.append(text)

    joined = "\n".join(texts).strip()

    if is_error:
        return {"success": False, "error": joined or "MCP 工具返回错误"}

    if structured is not None:
        if joined:
            return {
                "success": True,
                "result": {"text": joined, "structuredContent": structured},
            }
        return {"success": True, "result": structured}

    return {"success": True, "result": joined}


def _block_to_text(block: Any) -> str:
    """把单个 MCP 内容块转换为可读文本。"""
    if block is None:
        return ""
    if isinstance(block, str):
        return block

    block_type = _attr(block, "type", default=None)

    if isinstance(block, Mapping) and block_type is None:
        block_type = block.get("type")

    text = _attr(block, "text", default=None)
    if isinstance(text, str):
        return text

    if block_type == "image":
        mime = _attr(block, "mimeType", "mime_type", default="") or "未知"
        return f"[图片内容，MIME 类型：{mime}]"

    if block_type == "audio":
        mime = _attr(block, "mimeType", "mime_type", default="") or "未知"
        return f"[音频内容，MIME 类型：{mime}]"

    resource = _attr(block, "resource", default=None)
    if resource is not None:
        return _resource_to_text(resource)

    if isinstance(block, Mapping):
        return _safe_json(block)
    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        try:
            return _safe_json(model_dump())
        except Exception:
            pass
    return str(block)


def _resource_to_text(resource: Any) -> str:
    text = _attr(resource, "text", default=None)
    if isinstance(text, str) and text:
        return text
    uri = _attr(resource, "uri", default="") or ""
    return f"[资源：{uri}]" if uri else "[资源内容]"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)
