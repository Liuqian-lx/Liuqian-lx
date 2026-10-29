"""会话管理。

职责：
- 维护 messages 上下文（用户消息、assistant 消息、tool 结果）
- 驱动「模型回复 -> 工具调用 -> 工具结果回填 -> 继续回复」的闭环
- 加载与保存对话历史

本模块不包含任何 print/input，所有过程数据通过返回值与回调传递。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .llm_client import LLMClient, LLMError, ToolCall
from .tools import TOOLS, execute_tool, tool_result_content

TextCallback = Callable[[str], None]
ToolCallCallback = Callable[[ToolCall], None]
ToolResultCallback = Callable[["ToolEvent"], None]

DEFAULT_HISTORY_FILE = "chat_history.json"
DEFAULT_MAX_TOOL_ROUNDS = 8


@dataclass
class ToolEvent:
    """一次工具调用的完整记录，供界面展示。"""

    tool_call: ToolCall
    result: Dict[str, Any]
    content: str

    @property
    def success(self) -> bool:
        return bool(self.result.get("success"))


@dataclass
class SendResult:
    """一轮用户输入的最终结果。"""

    content: str = ""
    tool_events: List[ToolEvent] = field(default_factory=list)
    error: Optional[str] = None


class ChatSession:
    """一次完整对话的会话对象。"""

    def __init__(
        self,
        llm_client: LLMClient,
        history_file: Union[str, Path] = DEFAULT_HISTORY_FILE,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        self._llm = llm_client
        self._history_file = Path(history_file)
        self._tools = list(tools) if tools is not None else list(TOOLS)
        self._max_tool_rounds = max(1, int(max_tool_rounds))
        self._messages: List[Dict[str, Any]] = []
        self.last_error: Optional[str] = None
        self.load_history()

    # ------------------------------------------------------------------ 历史
    @property
    def history_file(self) -> Path:
        return self._history_file

    def get_history(self) -> List[Dict[str, Any]]:
        """返回当前消息上下文（浅拷贝，避免外部改动列表结构）。"""
        return list(self._messages)

    def load_history(self) -> List[Dict[str, Any]]:
        """从历史文件加载消息；文件不存在或损坏时以空上下文启动。"""
        self.last_error = None
        if not self._history_file.exists():
            self._messages = []
            return self._messages

        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("历史记录格式错误，应为消息列表")
            self._messages = [item for item in data if isinstance(item, dict)]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._messages = []
            self.last_error = f"读取对话历史失败：{exc}"
        return self._messages

    def save_history(self) -> bool:
        """把当前上下文写入历史文件，失败时记录 last_error 而不中断会话。"""
        try:
            parent = self._history_file.parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(self._messages, f, ensure_ascii=False, indent=2)
            return True
        except OSError as exc:
            self.last_error = f"保存对话历史失败：{exc}"
            return False

    # ------------------------------------------------------------------ 对话
    def send_message(
        self,
        text: str,
        on_text: Optional[TextCallback] = None,
        on_tool_call: Optional[ToolCallCallback] = None,
        on_tool_result: Optional[ToolResultCallback] = None,
    ) -> SendResult:
        """发送一条用户消息并完成工具调用闭环。

        回调均在当前线程同步触发：
        - on_text(delta)：模型每输出一个文本片段
        - on_tool_call(tool_call)：模型发起工具调用（即将执行）
        - on_tool_result(ToolEvent)：单个工具执行完成
        """
        self._messages.append({"role": "user", "content": text})
        events: List[ToolEvent] = []

        try:
            # 预留一轮给最终文本回复，其余为工具调用轮次
            for _ in range(self._max_tool_rounds + 1):
                response = self._llm.stream_chat(
                    self._messages,
                    tools=self._tools,
                    on_text=on_text,
                    on_tool_call=on_tool_call,
                )

                if not response.tool_calls:
                    self._messages.append(
                        {"role": "assistant", "content": response.content}
                    )
                    return SendResult(content=response.content, tool_events=events)

                # 记录 assistant 的工具调用消息，再逐个执行并回填结果
                self._messages.append(response.to_assistant_message())
                for call in response.tool_calls:
                    result = execute_tool(call.name, call.arguments)
                    content = tool_result_content(result)
                    self._messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": content,
                        }
                    )
                    event = ToolEvent(
                        tool_call=call,
                        result=result,
                        content=content,
                    )
                    events.append(event)
                    if on_tool_result is not None:
                        on_tool_result(event)

            notice = "工具调用轮次超过上限，已停止自动执行。"
            self._messages.append({"role": "assistant", "content": notice})
            return SendResult(content=notice, tool_events=events)

        except LLMError as exc:
            return SendResult(content="", tool_events=events, error=str(exc))
        except Exception as exc:
            return SendResult(
                content="",
                tool_events=events,
                error=f"会话执行失败：{exc}",
            )
        finally:
            # 每轮对话结束自动持久化，程序异常退出也不会丢失上下文
            self.save_history()
