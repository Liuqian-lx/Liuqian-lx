"""core 层：纯业务逻辑，不依赖任何界面框架。

对外导出配置、模型客户端、会话与工具能力；tui 层只能单向依赖本层。
"""

from .config import ConfigError, LLMConfig, load_config
from .llm_client import LLMClient, LLMError, LLMResponse, ToolCall
from .session import ChatSession, SendResult, ToolEvent
from .tools import TOOL_MAP, TOOLS, execute_tool

__all__ = [
    "ConfigError",
    "LLMConfig",
    "load_config",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "ToolCall",
    "ChatSession",
    "SendResult",
    "ToolEvent",
    "TOOLS",
    "TOOL_MAP",
    "execute_tool",
]
