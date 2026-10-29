"""Agent_L 程序唯一入口：加载配置 → 初始化 core 会话 → 启动 TUI。"""

from __future__ import annotations

import sys
from pathlib import Path

from core.config import ConfigError, load_config
from core.llm_client import LLMClient
from core.session import ChatSession
from tui.app import ChatApp

BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    try:
        config = load_config(BASE_DIR / "config.ini")
    except ConfigError as exc:
        print(f"启动失败：{exc}")
        return 1

    session = ChatSession(
        LLMClient(config),
        history_file=BASE_DIR / "chat_history.json",
    )
    ChatApp(session, model_name=config.model_name).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
