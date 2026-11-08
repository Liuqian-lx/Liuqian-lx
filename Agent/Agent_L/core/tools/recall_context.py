"""recallContext 工具：检索上下文压缩归档中的原始历史。

当压缩摘要缺少某些历史细节时，大模型可以调用本工具在
``.agents/context/*.jsonl`` 中做本地全文关键词检索。

参数：
- id：可选，指定归档编号（如 20261022-153000）；
- text：必需，关键词或文本内容（多个词以空格分隔时要求全部命中）。
"""

from __future__ import annotations

from typing import Any, Dict

from ..context_manager import get_active_context_store

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "recallContext",
            "description": (
                "在上下文压缩归档中检索历史对话的原始记录。"
                "当压缩摘要缺少某些细节（文件路径、命令、错误信息、旧决策等）时使用。"
                "不传 id 时检索全部归档；返回匹配片段、归档编号和所在行号。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": (
                            "可选，指定需要检索的上下文归档编号，"
                            "例如 20261022-153000；省略时检索全部归档。"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "必需，需要查找的关键词或文本内容。"
                            "多个关键词用空格分隔时，要求全部出现在同一条消息中。"
                        ),
                    },
                },
                "required": ["text"],
            },
        },
    }
]


def recall_context(id: str = "", text: str = "") -> Dict[str, Any]:
    """在归档中检索历史内容；所有错误均以结构化结果返回。"""
    store = get_active_context_store()
    try:
        return store.search(text=text, archive_id=id or None)
    except Exception as exc:  # 检索失败不应中断会话
        return {"success": False, "error": f"检索上下文归档失败：{exc}"}


TOOL_MAP = {
    "recallContext": recall_context,
}
