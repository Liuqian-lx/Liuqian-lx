"""会话管理。

职责：
- 维护 messages 上下文（用户消息、assistant 消息、tool 结果）
- 驱动「模型回复 -> 工具调用 -> 工具结果回填 -> 继续回复」的闭环
- 加载与保存对话历史

本模块不包含任何 print/input，所有过程数据通过返回值与回调传递。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .context_manager import (
    COMPACTION_SYSTEM_PROMPT,
    DEFAULT_SUMMARY_TOKENS,
    ContextManager,
    ContextUsage,
    format_archive_note,
    format_transcript,
    set_active_context_store,
)
from .llm_client import LLMClient, LLMError, ToolCall
from .skills import SkillManager, set_active_manager
from .tools import TOOLS, execute_tool, tool_result_content

TextCallback = Callable[[str], None]
ToolCallCallback = Callable[[ToolCall], None]
ToolResultCallback = Callable[["ToolEvent"], None]
UsageCallback = Callable[[ContextUsage], None]

DEFAULT_HISTORY_FILE = "chat_history.json"
DEFAULT_MAX_TOOL_ROUNDS = 8

# Skill 详细内容按需加载，系统提示只描述「有哪些 Skill、如何加载」。
# 无可用 Skill 时不注入任何 system 消息，保持原有消息结构不变。
BASE_SYSTEM_PROMPT = (
    "你是 Agent_L，一个运行在终端中的智能助手。"
    "可以调用工具完成文件操作、联网搜索、网页抓取、命令行执行和 Skill 加载等任务。"
    "请根据用户需求选择合适的工具，并基于工具返回的结果给出准确、简洁的中文回答。"
)


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


@dataclass
class CompactResult:
    """一次上下文压缩的结果。"""

    success: bool = False
    summary: str = ""
    before_text: str = ""
    archive_id: str = ""
    archive_path: Optional[str] = None
    message_count: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    error: Optional[str] = None


class ChatSession:
    """一次完整对话的会话对象。"""

    def __init__(
        self,
        llm_client: LLMClient,
        history_file: Union[str, Path] = DEFAULT_HISTORY_FILE,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        project_root: Optional[Union[str, Path]] = None,
        context_window: Optional[int] = None,
        compact_target_tokens: int = DEFAULT_SUMMARY_TOKENS,
    ):
        self._llm = llm_client
        self._history_file = Path(history_file)
        self._tools = list(tools) if tools is not None else list(TOOLS)
        self._max_tool_rounds = max(1, int(max_tool_rounds))
        self._messages: List[Dict[str, Any]] = []
        self.last_error: Optional[str] = None
        self._compacting = False

        # 会话初始化阶段只扫描 Skill 元数据；默认以程序启动时的工作目录为项目根
        self._skill_manager = SkillManager(
            project_root if project_root is not None else os.getcwd()
        )
        set_active_manager(self._skill_manager)

        # 上下文统计、归档目录与 recallContext 共用同一个项目根
        self._context = ContextManager(
            project_root=self._skill_manager.project_root,
            context_window=context_window,
            summary_target=compact_target_tokens,
        )
        set_active_context_store(self._context.archive_store)

        self._system_prompt = self._build_system_prompt()

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
        self._context.reset_usage()
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

    # ------------------------------------------------------------------ 上下文
    @property
    def context_window(self) -> int:
        return self._context.context_window

    @property
    def context_window_is_default(self) -> bool:
        return self._context.window_is_default

    @property
    def is_compacting(self) -> bool:
        """压缩期间禁止执行其他任务与工具。"""
        return self._compacting

    def get_context_usage(self) -> ContextUsage:
        """当前上下文使用量；优先使用最近一次 API usage，否则本地估算。"""
        return self._context.usage(
            self._messages,
            system_prompt=self._system_prompt,
            tools=self._tools,
        )

    @property
    def needs_compact(self) -> bool:
        return self.get_context_usage().needs_compact

    def compact(self, on_text: Optional[TextCallback] = None) -> CompactResult:
        """归档原始上下文并调用 LLM 生成摘要，成功后才替换历史消息。

        流程严格遵循：保存原始归档 -> 生成摘要 -> 替换上下文。
        任一步失败都保留原有上下文，返回带 error 的结果。
        """
        if self._compacting:
            return CompactResult(error="上下文压缩已在进行中，请稍候。")
        if not self._messages:
            return CompactResult(error="当前上下文为空，无需压缩。")

        self._compacting = True
        try:
            set_active_context_store(self._context.archive_store)
            before_usage = self.get_context_usage()
            before_text = format_transcript(self._messages)

            # 1. 原始上下文必须先完整落盘，失败则直接终止压缩
            try:
                archive = self._context.save_archive(list(self._messages))
            except Exception as exc:
                return CompactResult(
                    error=f"保存原始上下文归档失败，已保留原有上下文：{exc}"
                )

            # 2. 仅允许调用 LLM 生成摘要，不传入工具、也不执行任何工具
            try:
                summary = self._generate_summary(before_text, on_text)
            except LLMError as exc:
                return CompactResult(
                    error=f"生成上下文摘要失败，已保留原有上下文：{exc}",
                    archive_id=archive.id,
                    archive_path=str(archive.path),
                    before_text=before_text,
                )
            except Exception as exc:
                return CompactResult(
                    error=f"生成上下文摘要失败，已保留原有上下文：{exc}",
                    archive_id=archive.id,
                    archive_path=str(archive.path),
                    before_text=before_text,
                )

            if not summary.strip():
                return CompactResult(
                    error="大模型未返回有效的上下文摘要，已保留原有上下文。",
                    archive_id=archive.id,
                    archive_path=str(archive.path),
                    before_text=before_text,
                )

            # 3. 用摘要替换历史消息，System Prompt 与工具定义保持原样
            note = format_archive_note(archive.id)
            summary_with_note = f"{summary.strip()}\n\n{note}"
            self._messages = [
                {
                    "role": "user",
                    "content": (
                        "【历史上下文摘要】以下是此前对话压缩生成的摘要，"
                        "供后续任务继续使用：\n\n"
                        f"{summary_with_note}"
                    ),
                }
            ]
            self._context.reset_usage()
            self.save_history()
            after_usage = self.get_context_usage()

            return CompactResult(
                success=True,
                summary=summary_with_note,
                before_text=before_text,
                archive_id=archive.id,
                archive_path=str(archive.path),
                message_count=archive.message_count,
                tokens_before=before_usage.tokens,
                tokens_after=after_usage.tokens,
            )
        finally:
            self._compacting = False

    def _generate_summary(
        self, transcript: str, on_text: Optional[TextCallback]
    ) -> str:
        """调用 LLM 生成摘要；不传 tools，保证压缩期间不会触发 Function Calling。"""
        response = self._llm.stream_chat(
            [
                {"role": "system", "content": COMPACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "以下是需要压缩的会话历史原文：\n\n" + transcript,
                },
            ],
            tools=None,
            on_text=on_text,
        )
        # 即使模型返回 tool_calls，压缩流程也一律忽略，不执行任何工具
        return response.content or ""

    def _record_usage(self, response: Any) -> ContextUsage:
        """记录一次模型响应携带的 usage，并返回最新使用量。"""
        self._context.record_api_usage(getattr(response, "usage", None))
        return self.get_context_usage()

    # ------------------------------------------------------------------ Skill
    @property
    def system_prompt(self) -> str:
        """注入 Skill 列表后的系统提示；无可用 Skill 时为空字符串。"""
        return self._system_prompt

    @property
    def skill_manager(self) -> SkillManager:
        return self._skill_manager

    def _build_system_prompt(self) -> str:
        section = self._skill_manager.build_prompt_section()
        if not section:
            return ""
        return f"{BASE_SYSTEM_PROMPT}\n\n{section}"

    def _build_messages(self) -> List[Dict[str, Any]]:
        """系统提示只在本次请求中前置，不写入历史文件，避免重复持久化。"""
        if not self._system_prompt:
            return self._messages
        return [{"role": "system", "content": self._system_prompt}, *self._messages]

    # ------------------------------------------------------------------ 对话
    def send_message(
        self,
        text: str,
        on_text: Optional[TextCallback] = None,
        on_tool_call: Optional[ToolCallCallback] = None,
        on_tool_result: Optional[ToolResultCallback] = None,
        on_usage: Optional[UsageCallback] = None,
    ) -> SendResult:
        """发送一条用户消息并完成工具调用闭环。

        回调均在当前线程同步触发：
        - on_text(delta)：模型每输出一个文本片段
        - on_tool_call(tool_call)：模型发起工具调用（即将执行）
        - on_tool_result(ToolEvent)：单个工具执行完成
        - on_usage(ContextUsage)：每次模型响应后报告上下文使用量
        """
        if self._compacting:
            return SendResult(error="上下文压缩进行中，暂不能处理新的任务。")

        # 达到阈值后暂停接受普通提示词，必须先执行 /compact
        current_usage = self.get_context_usage()
        if current_usage.needs_compact:
            return SendResult(
                error=(
                    f"上下文使用量已达 {current_usage.percent:.1f}%"
                    f"（阈值 {current_usage.threshold * 100:.0f}%），"
                    "请先执行 /compact 命令压缩上下文后再继续。"
                )
            )

        self._messages.append({"role": "user", "content": text})
        self._context.reset_usage()
        events: List[ToolEvent] = []
        # 绑定本次会话的 SkillManager / 归档目录，保证工具读取正确的位置
        set_active_manager(self._skill_manager)
        set_active_context_store(self._context.archive_store)

        try:
            # 预留一轮给最终文本回复，其余为工具调用轮次
            for _ in range(self._max_tool_rounds + 1):
                response = self._llm.stream_chat(
                    self._build_messages(),
                    tools=self._tools,
                    on_text=on_text,
                    on_tool_call=on_tool_call,
                )

                # 每次 LLM 响应后刷新 Token 使用量
                usage = self._record_usage(response)
                if on_usage is not None:
                    on_usage(usage)

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

                # 工具结果已追加到上下文，之前那次 API usage 不再代表最新长度
                self._context.reset_usage()

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
