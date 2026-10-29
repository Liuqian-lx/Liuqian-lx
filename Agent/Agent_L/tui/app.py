"""Textual 主应用。

界面层只负责渲染、事件与调用 core.ChatSession；
模型调用、工具执行、历史持久化全部由 core 层完成。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button

from core.llm_client import ToolCall
from core.session import ChatSession, SendResult, ToolEvent

from .components import (
    ChatInput,
    HeaderBar,
    InputArea,
    MessageView,
    StatusBar,
)


class ChatApp(App):
    """深色聊天界面：顶部标题栏 + 消息流 + 多行输入 + 状态栏。"""

    TITLE = "Agent_L"
    SUB_TITLE = "文件助手"

    BINDINGS = [
        Binding("ctrl+l", "clear_messages", "清空界面"),
        Binding("ctrl+s", "save_history", "保存历史"),
        Binding("ctrl+q", "quit", "退出"),
    ]

    CSS = """
    Screen {
        background: #15191e;
        color: #d6dee7;
    }

    /* ------------------------------------------------------------ 顶部栏 */
    HeaderBar {
        dock: top;
        width: 100%;
        height: 1;
        padding: 0 2;
        background: #1b2027;
        align-vertical: middle;
    }

    .header-title {
        width: 1fr;
        height: 1;
        color: #bccbd9;
        text-style: bold;
    }

    .header-status {
        width: auto;
        height: 1;
        color: #8b98a5;
        text-align: right;
    }

    /* ------------------------------------------------------------ 消息区 */
    MessageView {
        height: 1fr;
        padding: 1 3 0 3;
        background: #15191e;
        scrollbar-color: #33404c;
        scrollbar-background: #15191e;
        scrollbar-size-vertical: 1;
    }

    MessageRow {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }

    .user-row {
        align-horizontal: right;
    }

    .assistant-row {
        align-horizontal: left;
    }

    .center-row {
        align-horizontal: center;
    }

    MessageBubble {
        width: auto;
        max-width: 76%;
        height: auto;
        padding: 0 2;
    }

    .bubble.user {
        background: #2a3a4a;
        color: #eef3f8;
    }

    .bubble.assistant {
        background: #20262d;
        color: #c8d2dc;
        border-left: thick #5f7d96;
        padding: 0 2 0 1;
    }

    .bubble.error,
    .bubble.notice {
        width: auto;
        max-width: 90%;
        background: transparent;
        border: none;
        padding: 0 1;
    }

    .bubble.error {
        color: #cf8b8b;
    }

    .bubble.notice {
        color: #7f8b98;
    }

    .bubble-role {
        width: auto;
        height: auto;
        color: #8b98a5;
    }

    .bubble-body {
        width: auto;
        height: auto;
        margin: 0;
        padding: 0;
        background: transparent;
    }

    .bubble.user .bubble-body {
        color: #eef3f8;
    }

    .bubble.assistant .bubble-body {
        color: #c8d2dc;
    }

    .bubble-time {
        width: 100%;
        height: auto;
        color: #8fa3b5;
        text-align: right;
    }

    /* ------------------------------------------------------------ 工具卡片 */
    .tool-call-view {
        width: 86%;
        height: auto;
        margin: 0 0 1 0;
    }

    .tool-collapsible {
        width: 100%;
        height: auto;
        background: #1b2128;
        border: solid #2b333c;
        padding: 0 1;
    }

    .tool-collapsible CollapsibleTitle {
        color: #a9b7c5;
    }

    .tool-body {
        width: 100%;
        height: auto;
    }

    .tool-section {
        width: 100%;
        height: auto;
        color: #7d8894;
        margin: 1 0 0 0;
    }

    .tool-code {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: #12161a;
        color: #b9c6d3;
        border-left: thick #3d4c5a;
    }

    .tool-code-muted {
        color: #7f8b98;
    }

    .tool-code-error {
        background: #2a1c1f;
        color: #d99a9a;
        border-left: thick #a86565;
    }

    /* ------------------------------------------------------------ 思考动画 */
    .thinking-row {
        height: auto;
        margin: 0 0 1 0;
    }

    .thinking-label {
        width: auto;
        height: auto;
        padding: 0 1;
        color: #7d9bb5;
    }

    /* ------------------------------------------------------------ 输入区 */
    InputArea {
        width: 100%;
        height: auto;
        padding: 0 3 1 3;
        background: #15191e;
        border-top: solid #242b33;
    }

    #chat-input {
        width: 100%;
        height: 4;
        background: #1e242b;
        color: #e2e9f0;
        border: tall #33404c;
        padding: 0 1;
    }

    #chat-input:focus {
        border: tall #6f8fa8;
    }

    #chat-input .text-area--placeholder {
        color: #6a7682;
    }

    #input-actions {
        width: 100%;
        height: 3;
        align-vertical: middle;
    }

    .input-hint {
        width: 1fr;
        height: auto;
        padding: 0 1;
        color: #6f7b87;
    }

    #send-button {
        width: 10;
        height: 3;
        background: #3a5064;
        color: #eef3f8;
        border: none;
        text-style: bold;
    }

    #send-button:hover {
        background: #476178;
    }

    #send-button:disabled {
        background: #262e36;
        color: #6f7b87;
    }

    /* ------------------------------------------------------------ 状态栏 */
    StatusBar {
        dock: bottom;
        width: 100%;
        height: 1;
        padding: 0 2;
        background: #1b2027;
        color: #7f8b98;
        align-vertical: middle;
    }

    #status-count {
        width: 1fr;
        height: 1;
        color: #8b98a5;
    }

    #status-state {
        width: auto;
        height: 1;
        color: #9fb3c6;
    }

    #status-keys {
        width: 1fr;
        height: 1;
        color: #6f7b87;
        text-align: right;
    }
    """

    def __init__(self, session: ChatSession, model_name: str = "未知模型"):
        super().__init__()
        self._session = session
        self._model_name = model_name
        self._busy = False
        self._quitting = False
        self._active_bubble = None

        self._view: Optional[MessageView] = None
        self._input: Optional[ChatInput] = None
        self._header: Optional[HeaderBar] = None
        self._status: Optional[StatusBar] = None
        self._send_button: Optional[Button] = None

    # ------------------------------------------------------------------ 布局
    def compose(self) -> ComposeResult:
        yield HeaderBar(self._model_name)
        yield MessageView(id="messages")
        yield InputArea(id="input-area")
        yield StatusBar()

    def on_mount(self) -> None:
        self._view = self.query_one(MessageView)
        self._input = self.query_one(ChatInput)
        self._header = self.query_one(HeaderBar)
        self._status = self.query_one(StatusBar)
        self._send_button = self.query_one("#send-button", Button)

        self._restore_history()
        if self._session.last_error:
            self._view.add_notice(self._session.last_error)

        self._refresh_message_count()
        self._status.set_state("就绪")
        self._header.set_online(None)
        self._input.focus()

    def on_unmount(self) -> None:
        # 双保险：退出时再保存一次
        self._session.save_history()

    # ------------------------------------------------------------------ 历史
    def _restore_history(self) -> None:
        """把 core 中的历史消息完整还原为气泡与工具卡片。"""
        if self._view is None:
            return

        history = self._session.get_history()
        tool_results = {
            message.get("tool_call_id"): message.get("content")
            for message in history
            if message.get("role") == "tool"
        }

        for message in history:
            role = message.get("role")
            content = message.get("content") or ""

            if role == "user":
                if content:
                    self._view.add_user_message(content)
            elif role == "assistant":
                if content:
                    self._view.add_assistant_message(content)
                for raw_call in message.get("tool_calls") or []:
                    function = raw_call.get("function") or {}
                    name = function.get("name") or ""
                    if not name:
                        continue
                    call = ToolCall(
                        id=raw_call.get("id") or "",
                        name=name,
                        arguments=function.get("arguments") or "",
                    )
                    result = self._parse_history_result(tool_results.get(call.id))
                    self._view.add_tool_result(call, result)

        self._view.scroll_to_end()

    @staticmethod
    def _parse_history_result(content: Any) -> dict:
        if content is None:
            return {"success": True, "result": ""}
        if isinstance(content, dict):
            return content
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            return {"success": True, "result": content}
        if isinstance(data, dict):
            return data
        return {"success": True, "result": data}

    # ------------------------------------------------------------------ 输入
    @on(ChatInput.Submitted)
    def _handle_submit(self, event: ChatInput.Submitted) -> None:
        if self._busy:
            return
        self._start_turn(event.value)

    @on(Button.Pressed, "#send-button")
    def _handle_send_button(self, event: Button.Pressed) -> None:
        if self._busy or self._input is None:
            return
        text = self._input.text.strip()
        if text:
            self._start_turn(text)
        else:
            self._input.focus()

    def _start_turn(self, text: str) -> None:
        if self._view is None or self._input is None:
            return

        text = text.strip()
        if not text:
            return

        self._busy = True
        self._active_bubble = None

        self._input.remember(text)
        self._input.clear_input()
        self._view.add_user_message(text, datetime.now().strftime("%H:%M"))
        self._view.show_thinking("思考中")

        self._refresh_message_count()
        self._status.set_state("等待回复…")
        self._header.set_online(None)
        self._set_busy_ui(True)
        self._respond(text)

    def _set_busy_ui(self, busy: bool) -> None:
        if self._input is None or self._send_button is None:
            return
        self._input.disabled = busy
        self._send_button.disabled = busy
        if busy:
            self.set_focus(None)
        else:
            self._input.focus()

    # ------------------------------------------------------------------ 后台
    @work(thread=True, exclusive=True, group="chat")
    def _respond(self, text: str) -> None:
        try:
            result = self._session.send_message(
                text,
                on_text=self._thread_text,
                on_tool_call=self._thread_tool_call,
                on_tool_result=self._thread_tool_result,
            )
        except Exception as exc:  # core 已捕获大部分异常，这里仅兜底
            result = SendResult(content="", error=f"会话执行失败：{exc}")

        self._call_ui(self._finish_turn, result)

    # 以下回调运行在工作线程，必须切回 UI 线程再操作控件
    def _thread_text(self, delta: str) -> None:
        self._call_ui(self._append_text, delta)

    def _thread_tool_call(self, tool_call: ToolCall) -> None:
        self._call_ui(self._show_tool_call, tool_call)

    def _thread_tool_result(self, event: ToolEvent) -> None:
        self._call_ui(self._show_tool_result, event)

    def _call_ui(self, callback: Callable[..., Any], *args: Any) -> None:
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            # 应用正在退出，忽略未送达的界面更新
            pass

    # ------------------------------------------------------------------ 界面更新
    def _append_text(self, delta: str) -> None:
        if self._view is None:
            return
        self._view.hide_thinking()
        if self._active_bubble is None:
            self._active_bubble = self._view.add_assistant_message()
            self._refresh_message_count()
        self._active_bubble.append_text(delta)
        self._view.scroll_to_end()
        self._status.set_state("正在回复…")

    def _show_tool_call(self, tool_call: ToolCall) -> None:
        if self._view is None:
            return
        self._view.add_tool_call(tool_call)
        # 工具卡片之后的文本应另起一个助手气泡，保证消息顺序正确
        self._active_bubble = None
        self._view.show_thinking("正在执行工具")
        self._refresh_message_count()
        self._status.set_state(f"执行工具：{tool_call.name}")

    def _show_tool_result(self, event: ToolEvent) -> None:
        if self._view is None:
            return
        self._view.update_tool_result(event)
        self._view.show_thinking("思考中")
        self._status.set_state("工具完成，等待回复…")

    def _finish_turn(self, result: SendResult) -> None:
        if self._view is not None:
            self._view.hide_thinking()
            if result.error:
                self._view.add_error(result.error)

        if result.error:
            self._status.set_state("请求失败，可重新发送")
            if self._header is not None:
                self._header.set_online(False)
        else:
            self._status.set_state("就绪")
            if self._header is not None:
                self._header.set_online(True)

        self._refresh_message_count()
        self._active_bubble = None
        self._busy = False
        self._set_busy_ui(False)

    def _refresh_message_count(self) -> None:
        if self._view is not None and self._status is not None:
            self._status.set_message_count(self._view.message_count)

    # ------------------------------------------------------------------ 快捷键
    def action_clear_messages(self) -> None:
        if self._busy:
            self.notify("回复进行中，暂不能清屏", severity="warning")
            return
        if self._view is None:
            return
        self._view.clear_messages()
        self._active_bubble = None
        self._refresh_message_count()
        self._status.set_state("界面已清空，本地历史保留")

    def action_save_history(self) -> None:
        if self._session.save_history():
            self._status.set_state("对话历史已保存")
            self.notify("对话历史已保存", timeout=2)
        else:
            message = self._session.last_error or "保存对话历史失败"
            if self._view is not None:
                self._view.add_error(message)
                self._refresh_message_count()
            self._status.set_state("保存失败")
            self.notify(message, severity="error", timeout=3)

    async def action_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        saved = self._session.save_history()
        message = "对话历史已保存，正在退出…" if saved else "历史保存失败，正在退出…"
        if self._status is not None:
            self._status.set_state(message)
        self.notify(message, timeout=1)
        self.set_timer(0.6, self.exit)
