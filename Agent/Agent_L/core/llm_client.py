"""大模型客户端。

封装 OpenAI 兼容接口的流式调用：
- 逐块聚合 delta.content，并通过 on_text 回调实时抛出文本片段
- 按 index 聚合 delta.tool_calls，流结束后通过 on_tool_call 回调抛出完整工具调用
- 所有 API / 网络异常统一包装为 LLMError，由会话层决定如何反馈
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from openai import OpenAI

from .config import LLMConfig

TextCallback = Callable[[str], None]
ToolCallCallback = Callable[["ToolCall"], None]


class LLMError(Exception):
    """大模型调用失败。"""


@dataclass
class ToolCall:
    """一个完整的工具调用（由流式分片聚合而来）。"""

    id: str
    name: str
    arguments: str = ""

    def parse_arguments(self) -> Dict[str, Any]:
        """解析 JSON 参数，空字符串视为无参数。"""
        raw = (self.arguments or "").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        return data

    def as_message_part(self) -> Dict[str, Any]:
        """转换为 assistant 消息中的 tool_calls 元素。"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class LLMResponse:
    """一次流式响应的聚合结果。"""

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)

    def to_assistant_message(self) -> Dict[str, Any]:
        """转换为可写入 messages 的 assistant 消息。"""
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": self.content or None,
        }
        if self.tool_calls:
            message["tool_calls"] = [tc.as_message_part() for tc in self.tool_calls]
        return message


class LLMClient:
    """流式聊天客户端。"""

    def __init__(self, config: LLMConfig, client: Optional[OpenAI] = None):
        self._config = config
        try:
            self._client = client or OpenAI(
                base_url=config.base_url,
                api_key=config.api_key,
            )
        except Exception as exc:
            raise LLMError(f"初始化大模型客户端失败：{exc}") from exc

    @property
    def model_name(self) -> str:
        return self._config.model_name

    def stream_chat(
        self,
        messages: Sequence[Dict[str, Any]],
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        on_text: Optional[TextCallback] = None,
        on_tool_call: Optional[ToolCallCallback] = None,
    ) -> LLMResponse:
        """发起一次流式对话，返回聚合后的文本与工具调用。

        on_text：每收到一个文本片段立即回调。
        on_tool_call：流结束后，对每个聚合完成的工具调用回调一次。
        """
        request: Dict[str, Any] = {
            "model": self._config.model_name,
            "messages": messages,
            "stream": True,
        }
        if tools:
            request["tools"] = tools

        try:
            stream = self._client.chat.completions.create(**request)
        except Exception as exc:
            raise LLMError(f"API 调用失败：{exc}") from exc

        content_parts: List[str] = []
        tool_calls: Dict[int, Dict[str, str]] = {}

        try:
            for chunk in stream:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = choices[0].delta
                if delta is None:
                    continue

                if delta.content:
                    content_parts.append(delta.content)
                    if on_text is not None:
                        on_text(delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        index = tc.index if tc.index is not None else 0
                        if index not in tool_calls:
                            tool_calls[index] = {"id": "", "name": "", "arguments": ""}
                        entry = tool_calls[index]
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                entry["name"] = tc.function.name
                            if tc.function.arguments:
                                entry["arguments"] += tc.function.arguments
        except Exception as exc:
            # 网络中断等流式读取异常
            raise LLMError(f"流式响应读取失败：{exc}") from exc

        assembled = [
            ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=entry["arguments"],
            )
            for _, entry in sorted(tool_calls.items())
        ]

        for call in assembled:
            if on_tool_call is not None:
                on_tool_call(call)

        return LLMResponse(content="".join(content_parts), tool_calls=assembled)
