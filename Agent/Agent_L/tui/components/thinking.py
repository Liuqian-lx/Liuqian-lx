"""助手思考 / 工具执行中的动画指示器。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class ThinkingIndicator(Horizontal):
    """消息流中的「思考中…」打字动画。"""

    def __init__(self) -> None:
        super().__init__(classes="msg-row assistant-row thinking-row")
        self._label = Static("", classes="thinking-label", markup=False)
        self._frame = 0
        self._status = "思考中"
        self._timer = None

    def compose(self) -> ComposeResult:
        yield self._label

    def on_mount(self) -> None:
        self._refresh_label()
        self._timer = self.set_interval(0.3, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(_SPINNER)
        self._refresh_label()

    def _refresh_label(self) -> None:
        dots = "." * (self._frame % 4)
        self._label.update(f"{_SPINNER[self._frame]}  {self._status}{dots}")

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh_label()
