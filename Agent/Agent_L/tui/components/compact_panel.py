"""上下文压缩结果浮动面板。

左右两栏分别展示压缩前原文与压缩后摘要，均可滚动，右下角提供关闭按钮。
面板内容过长时只展示前 MAX_PANEL_CHARS 个字符，完整原文已保存在
``.agents/context/`` 归档中。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

MAX_PANEL_CHARS = 60_000


class CompactPanel(ModalScreen[None]):
    """两栏对比的模态浮层，Esc 或「关闭」按钮退出。"""

    BINDINGS = [Binding("escape", "close", "关闭")]

    DEFAULT_CSS = """
    CompactPanel {
        align: center middle;
        background: #0b0e11 70%;
    }

    #compact-dialog {
        width: 94%;
        height: 88%;
        background: #1b2027;
        border: thick #4b6b85;
        padding: 1 2;
    }

    #compact-title {
        width: 100%;
        height: 1;
        color: #cfe0ef;
        text-style: bold;
    }

    #compact-meta {
        width: 100%;
        height: 1;
        color: #7f8b98;
    }

    #compact-columns {
        width: 100%;
        height: 1fr;
        margin: 1 0;
    }

    .compact-column {
        width: 1fr;
        height: 100%;
        padding: 0 1;
    }

    .compact-column-title {
        width: 100%;
        height: 1;
        color: #9fb3c6;
        text-style: bold;
    }

    .compact-scroll {
        width: 100%;
        height: 1fr;
        background: #12161a;
        border: solid #2b333c;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: #33404c;
        scrollbar-background: #12161a;
    }

    .compact-text {
        width: 100%;
        height: auto;
        color: #b9c6d3;
    }

    #compact-actions {
        width: 100%;
        height: 3;
        align-horizontal: right;
        align-vertical: middle;
    }

    #compact-close {
        width: 12;
        height: 3;
        background: #3a5064;
        color: #eef3f8;
        border: none;
        text-style: bold;
    }

    #compact-close:hover {
        background: #476178;
    }
    """

    def __init__(self, before_text: str, after_text: str, meta: str = ""):
        super().__init__()
        self._before = self._clip(before_text, "完整原文已保存在归档文件中")
        self._after = self._clip(after_text, "完整摘要已写入当前会话历史")
        self._meta = meta

    @staticmethod
    def _clip(text: str, hint: str) -> str:
        text = text or ""
        if len(text) <= MAX_PANEL_CHARS:
            return text
        return (
            text[:MAX_PANEL_CHARS]
            + f"\n\n…（内容超过 {MAX_PANEL_CHARS} 字符，仅展示前 {MAX_PANEL_CHARS} 字符，{hint}）"
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="compact-dialog"):
            yield Static("上下文压缩结果", id="compact-title", markup=False)
            yield Static(self._meta, id="compact-meta", markup=False)
            with Horizontal(id="compact-columns"):
                with Vertical(classes="compact-column"):
                    yield Static(
                        "压缩前原文", classes="compact-column-title", markup=False
                    )
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(self._before, classes="compact-text", markup=False)
                with Vertical(classes="compact-column"):
                    yield Static(
                        "压缩后摘要", classes="compact-column-title", markup=False
                    )
                    with VerticalScroll(classes="compact-scroll"):
                        yield Static(self._after, classes="compact-text", markup=False)
            with Horizontal(id="compact-actions"):
                yield Button("关闭", id="compact-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "compact-close":
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
