"""底部输入区。

- Enter 发送，Ctrl+Enter（兼容 Shift+Enter）换行
- ↑ / ↓ 翻看历史发送记录（多行编辑时优先移动光标）
- 输入框随内容行数自动增高
"""

from __future__ import annotations

from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static, TextArea

MIN_HEIGHT = 3
MAX_HEIGHT = 8


class ChatInput(TextArea):
    """支持发送、换行与历史记录的聊天输入框。"""

    BINDINGS = [
        ("up", "history_previous", "上一条历史"),
        ("down", "history_next", "下一条历史"),
    ]

    class Submitted(Message):
        """用户请求发送当前输入内容。"""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs):
        kwargs.setdefault("placeholder", "输入消息，Enter 发送，Ctrl+Enter 换行")
        kwargs.setdefault("id", "chat-input")
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._history_index: Optional[int] = None
        self._draft = ""

    # ------------------------------------------------------------------ 按键
    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
            return

        if event.key in ("ctrl+enter", "shift+enter"):
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return

        if event.is_printable or event.key in ("backspace", "delete"):
            self._history_index = None

        await super()._on_key(event)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """根据行数自动调整输入框高度（含边框）。"""
        lines = max(1, self.document.line_count)
        target = min(MAX_HEIGHT, max(MIN_HEIGHT, lines + 2))
        self.styles.height = target

    # ------------------------------------------------------------------ 历史
    def remember(self, text: str) -> None:
        """记录一条成功发送的消息。"""
        text = text.strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_index = None
        self._draft = ""

    def clear_input(self) -> None:
        self.load_text("")
        self._history_index = None
        self._draft = ""

    def action_history_previous(self) -> None:
        if not self._history:
            self.action_cursor_up()
            return

        if self._history_index is None:
            # 多行编辑且光标不在首行时，优先移动光标
            if not self.cursor_at_first_line:
                self.action_cursor_up()
                return
            self._draft = self.text
            self._history_index = len(self._history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)

        self._load_value(self._history[self._history_index])

    def action_history_next(self) -> None:
        if self._history_index is None:
            self.action_cursor_down()
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._load_value(self._history[self._history_index])
        else:
            self._history_index = None
            self._load_value(self._draft)

    def _load_value(self, value: str) -> None:
        self.load_text(value)
        self.move_cursor(self.document.end)


class InputArea(Vertical):
    """输入框 + 底部操作行（提示文字与发送按钮）。"""

    def compose(self) -> ComposeResult:
        yield ChatInput()
        with Horizontal(id="input-actions"):
            yield Static(
                "Enter 发送 · Ctrl+Enter 换行 · ↑↓ 历史",
                classes="input-hint",
            )
            yield Button("发送", id="send-button", variant="primary")
