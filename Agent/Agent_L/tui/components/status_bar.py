"""底部状态栏：消息条数 / 运行状态 / 快捷键提示。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class StatusBar(Horizontal):
    """三栏状态栏。"""

    def __init__(self) -> None:
        super().__init__(id="status-bar")
        self._count = Static("0 条消息", id="status-count", markup=False)
        self._state = Static("就绪", id="status-state", markup=False)
        self._keys = Static(
            "Enter 发送 · Ctrl+L 清屏 · Ctrl+S 保存 · Ctrl+Q 退出",
            id="status-keys",
            markup=False,
        )

    def compose(self) -> ComposeResult:
        yield self._count
        yield self._state
        yield self._keys

    def set_message_count(self, count: int) -> None:
        self._count.update(f"{count} 条消息")

    def set_state(self, text: str) -> None:
        self._state.update(text)
