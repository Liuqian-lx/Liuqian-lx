"""顶部固定标题栏：应用名 + 模型名 + 连接状态圆点。"""

from __future__ import annotations

from typing import Optional

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class HeaderBar(Horizontal):
    """左侧标题、右侧模型与在线状态。"""

    def __init__(self, model_name: str):
        super().__init__(id="header-bar")
        self._model_name = model_name
        self._online: Optional[bool] = None
        self._title = Static("◆ Agent_L 文件助手", classes="header-title", markup=False)
        self._status = Static("", classes="header-status")

    def compose(self) -> ComposeResult:
        yield self._title
        yield self._status

    def on_mount(self) -> None:
        self._refresh()

    def set_online(self, online: Optional[bool]) -> None:
        """True 在线（绿）/ False 离线（灰）/ None 连接中。"""
        self._online = online
        self._refresh()

    def _refresh(self) -> None:
        if self._online is True:
            dot = "[#7fb08a]●[/] 在线"
        elif self._online is False:
            dot = "[#8a939d]●[/] 离线"
        else:
            dot = "[#8a939d]◌[/] 连接中"
        self._status.update(f"{escape(self._model_name)}   {dot}")
