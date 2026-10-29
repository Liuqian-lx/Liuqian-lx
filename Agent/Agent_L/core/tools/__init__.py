"""工具注册与执行入口。

对外提供：
- TOOLS：合并后的工具 schema 列表
  （2 个内置工具 + 10 个文件工具 + 1 个联网搜索工具 + 1 个网页正文提取工具）
- TOOL_MAP：工具名 -> 可调用函数
- execute_tool(name, arguments)：统一解析参数、执行工具、捕获异常
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .builtin import TOOLS as BUILTIN_TOOLS
from .builtin import TOOL_MAP as BUILTIN_TOOL_MAP
from .file_ops import TOOLS as FILE_TOOLS
from .file_ops import TOOL_MAP as FILE_TOOL_MAP
from .web_fetch import TOOLS as WEB_FETCH_TOOLS
from .web_fetch import TOOL_MAP as WEB_FETCH_TOOL_MAP
from .web_search import TOOLS as WEB_SEARCH_TOOLS
from .web_search import TOOL_MAP as WEB_SEARCH_TOOL_MAP

TOOLS = BUILTIN_TOOLS + FILE_TOOLS + WEB_SEARCH_TOOLS + WEB_FETCH_TOOLS
TOOL_MAP = {
    **BUILTIN_TOOL_MAP,
    **FILE_TOOL_MAP,
    **WEB_SEARCH_TOOL_MAP,
    **WEB_FETCH_TOOL_MAP,
}

__all__ = ["TOOLS", "TOOL_MAP", "execute_tool", "tool_result_content"]


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
