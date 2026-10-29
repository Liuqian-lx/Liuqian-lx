"""消息滚动展示区。

- MessageBubble：用户（右侧）/ 助手（左侧）/ 系统、错误（居中）气泡
- ToolCallView：嵌入助手消息流的可折叠工具执行卡片
- ThinkingIndicator：思考 / 工具执行中的动画
- MessageView：按顺序挂载、自动滚动、清屏
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from rich.cells import cell_len
from rich.markdown import Markdown as RichMarkdown
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.geometry import Size
from textual.widgets import Collapsible, Static

from core.llm_client import ToolCall
from core.session import ToolEvent

from .thinking import ThinkingIndicator

_ROW_CLASS = {
    "user": "user-row",
    "assistant": "assistant-row",
    "tool": "assistant-row tool-row",
    "center": "center-row",
}


class MessageRow(Horizontal):
    """单条消息的横向容器，负责左 / 右 / 居中布局。"""

    def __init__(self, role: str, *children):
        classes = f"msg-row {_ROW_CLASS.get(role, 'center-row')}"
        super().__init__(*children, classes=classes)


class MarkdownBody(Static):
    """Markdown 内容区。

    Rich Markdown 的固有宽度测量偏小，会导致中文气泡被挤成窄条；
    这里按源文本的实际显示宽度计算，交给外层 max-width 控制上限。
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._source = ""

    def set_source(self, text: str) -> None:
        self._source = text
        self.update(RichMarkdown(text) if text else "")

    def get_content_width(self, container: Size, viewport: Size) -> int:
        if not self._source:
            return 0
        lines = self._source.splitlines() or [""]
        longest = max(cell_len(line) for line in lines)
        # 以视口宽度为上界，避免被尚未展开的父容器宽度反向压缩
        return min(longest, viewport.width)


class MessageBubble(Vertical):
    """消息气泡，支持流式追加文本。"""

    def __init__(
        self,
        role: str,
        text: str = "",
        timestamp: Optional[str] = None,
    ):
        super().__init__(classes=f"bubble {role}")
        self._role = role
        self._text = text
        self._timestamp = timestamp
        self._children: List = []

        if role == "assistant":
            self._children.append(Static("🤖 助手", classes="bubble-role", markup=False))
            # 用 Static 承载 Rich Markdown：挂载前也能安全流式更新
            self._body = MarkdownBody(classes="bubble-body", markup=False)
            self._refresh_body()
        else:
            self._body = Static(text, classes="bubble-body", markup=False)

        self._children.append(self._body)

        if role == "user" and timestamp:
            self._children.append(Static(timestamp, classes="bubble-time", markup=False))

    def compose(self) -> ComposeResult:
        yield from self._children

    @property
    def text(self) -> str:
        return self._text

    def append_text(self, delta: str) -> None:
        if not delta:
            return
        self._text += delta
        self._refresh_body()

    def set_text(self, text: str) -> None:
        self._text = text
        self._refresh_body()

    def _refresh_body(self) -> None:
        if self._role == "assistant":
            self._body.set_source(self._text)
        else:
            self._body.update(self._text)


class ToolCallView(Vertical):
    """工具调用卡片：默认展开，标题展示执行状态。

    成功使用绿色 ✓，失败使用红色 ✗；入参与返回结果以代码块样式展示，
    失败结果额外使用红色高亮。
    """

    def __init__(self, tool_call: ToolCall):
        super().__init__(classes="tool-call-view")
        self._call = tool_call
        self._arguments = tool_call.arguments or ""

        self._result_code = Static(
            "等待执行结果…",
            classes="tool-code tool-code-muted",
            markup=False,
        )
        body = Vertical(
            Static("入参", classes="tool-section", markup=False),
            Static(self._format_args(), classes="tool-code", markup=False),
            Static("返回结果", classes="tool-section", markup=False),
            self._result_code,
            classes="tool-body",
        )
        self._collapsible = Collapsible(
            body,
            title=self._title("running"),
            collapsed=False,
            classes="tool-collapsible",
        )

    def compose(self) -> ComposeResult:
        yield self._collapsible

    # ------------------------------------------------------------------ 内部
    def _title(self, state: str, success: bool = False) -> str:
        name = self._call.name
        if state == "running":
            return f"[#c9b27e]⏳[/] {name} · 执行中"
        if success:
            return f"[#7fb08a]✓[/] {name} · 成功"
        return f"[#cf8b8b]✗[/] {name} · 失败"

    def _format_args(self) -> str:
        raw = self._arguments.strip()
        if not raw:
            return "（无参数）"
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except (ValueError, TypeError):
            return raw

    @staticmethod
    def _format_result(result: dict) -> str:
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(result)

    # ------------------------------------------------------------------ 状态
    def set_result(self, result: dict) -> None:
        success = bool(result.get("success"))
        self._collapsible.title = self._title("done", success=success)
        self._result_code.set_class(not success, "tool-code-error")
        self._result_code.set_class(success, "tool-code-muted")
        self._result_code.update(self._format_result(result))


class MessageView(VerticalScroll):
    """消息列表容器：挂载、计数、思考动画与自动滚动。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tool_views: Dict[str, ToolCallView] = {}
        self._pending_views: List[ToolCallView] = []
        self._message_count = 0
        self._thinking: Optional[ThinkingIndicator] = None

    # ------------------------------------------------------------------ 气泡
    def add_user_message(self, text: str, timestamp: Optional[str] = None) -> MessageBubble:
        bubble = MessageBubble("user", text, timestamp)
        self._append_row("user", bubble)
        return bubble

    def add_assistant_message(self, text: str = "", timestamp: Optional[str] = None) -> MessageBubble:
        bubble = MessageBubble("assistant", text, timestamp)
        self._append_row("assistant", bubble)
        return bubble

    def add_error(self, text: str) -> MessageBubble:
        bubble = MessageBubble("error", f"✕  {text}")
        self._append_row("center", bubble)
        return bubble

    def add_notice(self, text: str) -> MessageBubble:
        bubble = MessageBubble("notice", text)
        self._append_row("center", bubble)
        return bubble

    # ------------------------------------------------------------------ 工具
    def add_tool_call(self, tool_call: ToolCall) -> ToolCallView:
        view = ToolCallView(tool_call)
        self._tool_views[tool_call.id] = view
        self._pending_views.append(view)
        self._append_row("tool", view)
        return view

    def add_tool_result(self, tool_call: ToolCall, result: dict) -> ToolCallView:
        """渲染历史记录中的工具调用及其结果。"""
        view = self.add_tool_call(tool_call)
        view.set_result(result)
        self._tool_views.pop(tool_call.id, None)
        if view in self._pending_views:
            self._pending_views.remove(view)
        return view

    def update_tool_result(self, event: ToolEvent) -> None:
        view = self._tool_views.pop(event.tool_call.id, None)
        if view is None and self._pending_views:
            # 兜底：模型未返回 tool_call id 时按调用顺序匹配
            view = self._pending_views[0]
        if view is None:
            return
        if view in self._pending_views:
            self._pending_views.remove(view)
        view.set_result(event.result)
        self.scroll_to_end()

    # ------------------------------------------------------------------ 思考
    def show_thinking(self, status: str = "思考中") -> None:
        if self._thinking is not None:
            self._thinking.set_status(status)
            return
        indicator = ThinkingIndicator()
        indicator.set_status(status)
        self._thinking = indicator
        self.mount(indicator)
        self.scroll_to_end()

    def set_thinking_status(self, status: str) -> None:
        if self._thinking is not None:
            self._thinking.set_status(status)

    def hide_thinking(self) -> None:
        if self._thinking is None:
            return
        indicator = self._thinking
        self._thinking = None
        indicator.remove()

    # ------------------------------------------------------------------ 其它
    @property
    def message_count(self) -> int:
        return self._message_count

    def clear_messages(self) -> None:
        self._tool_views.clear()
        self._pending_views.clear()
        self._message_count = 0
        self._thinking = None
        for child in list(self.children):
            child.remove()
        self.scroll_home(animate=False)

    def scroll_to_end(self) -> None:
        self.call_after_refresh(self.scroll_end, animate=False)

    def _append_row(self, role: str, widget) -> None:
        self._message_count += 1
        self.mount(MessageRow(role, widget))
        self.scroll_to_end()
