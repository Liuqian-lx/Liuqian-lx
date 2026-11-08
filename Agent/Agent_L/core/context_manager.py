"""上下文长度监控、原始上下文归档与历史检索。

设计目标（教学版，保持简单）：
- 不依赖向量数据库 / Embedding / 第三方检索框架；
- Token 数量优先使用模型 API 返回的 usage，取不到时按字符启发式估算；
- 压缩前把原始消息逐行写入 ``.agents/context/<编号>.jsonl``，可被
  ``recallContext`` 工具全文关键词检索；
- 模型上下文窗口优先读取 ``config.ini`` 的 ``context_window``，缺失时
  按 128k 估算，并在界面上标注「默认」。

本模块只使用 Python 标准库，不包含任何 print/input。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_COMPACT_THRESHOLD = 0.6
DEFAULT_SUMMARY_TOKENS = 5_000
CONTEXT_ARCHIVE_DIR = Path(".agents") / "context"

# 检索结果上限：避免一次 recall 再次撑满上下文
MAX_RECALL_RESULTS = 10
MAX_SNIPPET_CHARS = 400
MAX_RECALL_TOTAL_CHARS = 4_000

# 归档编号形如 20261022-153000，同一秒内重复时追加 -1、-2
_ARCHIVE_ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}(-[0-9]+)?$")

COMPACTION_SYSTEM_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

ARCHIVE_NOTE_TEMPLATE = (
    "此前上下文已于 {time} 完成压缩，原始上下文保存在编号为 {archive_id} 的归档文件中。"
    "如需查找历史信息，请使用 recallContext 工具。"
)


# ---------------------------------------------------------------- Token 估算
def estimate_tokens(text: Any) -> int:
    """粗略估算文本 Token 数。

    英文/ASCII 约 4 个字符 1 个 Token，中文等非 ASCII 字符按 1 字符 1 个
    Token 保守估算。估算只用于无法从 API 获得 usage 时的兜底。
    """
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii)


def estimate_messages_tokens(messages: Sequence[Dict[str, Any]]) -> int:
    """估算消息列表的 Token 数，包含角色、内容、工具调用参数与结果。"""
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            total += estimate_tokens(message)
            continue
        total += 4  # 每条消息的 role 分隔符等固定开销
        total += estimate_tokens(message.get("role") or "")
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif content is not None:
            total += estimate_tokens(json.dumps(content, ensure_ascii=False))
        for call in message.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            total += estimate_tokens(function.get("name") or "")
            total += estimate_tokens(function.get("arguments") or "")
        if message.get("tool_call_id"):
            total += estimate_tokens(str(message["tool_call_id"]))
    return total


def estimate_tools_tokens(tools: Optional[Sequence[Dict[str, Any]]]) -> int:
    """估算工具定义占用的 Token（与 API 的 prompt_tokens 口径保持一致）。"""
    if not tools:
        return 0
    try:
        return estimate_tokens(json.dumps(list(tools), ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- 使用量信息
@dataclass(frozen=True)
class ContextUsage:
    """某一时刻的上下文使用情况。"""

    tokens: int
    window: int
    threshold: float
    window_is_default: bool
    source: str = "estimate"  # api / estimate

    @property
    def ratio(self) -> float:
        if self.window <= 0:
            return 0.0
        return self.tokens / self.window

    @property
    def percent(self) -> float:
        return self.ratio * 100

    @property
    def needs_compact(self) -> bool:
        return self.ratio >= self.threshold

    def format_display(self) -> str:
        """TUI 顶栏文案：已用 k / 窗口 k · 百分比（默认）。"""
        used_k = f"{self.tokens / 1000:.1f}k"
        window_k = f"{self.window / 1000:g}k"
        default_mark = "（默认）" if self.window_is_default else ""
        return f"上下文 {used_k} / {window_k}{default_mark} · {self.percent:.1f}%"


# ---------------------------------------------------------------- 归档存储
@dataclass(frozen=True)
class ArchiveInfo:
    """一次归档的结果。"""

    id: str
    path: Path
    message_count: int


def format_archive_note(archive_id: str, when: Optional[datetime] = None) -> str:
    """生成追加到摘要末尾的归档说明。"""
    timestamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return ARCHIVE_NOTE_TEMPLATE.format(time=timestamp, archive_id=archive_id)


def format_transcript(messages: Sequence[Dict[str, Any]]) -> str:
    """把消息列表整理成便于模型阅读 / 界面展示的纯文本。"""
    lines: List[str] = []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            lines.extend([f"[{index}] {message}", ""])
            continue

        role = message.get("role") or "unknown"
        lines.append(f"[{index}] role={role}")
        content = message.get("content")
        if isinstance(content, str):
            if content:
                lines.append(content)
        elif content is not None:
            lines.append(json.dumps(content, ensure_ascii=False))

        for call in message.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            lines.append(
                "tool_call id={id} name={name} arguments={arguments}".format(
                    id=(call or {}).get("id") or "",
                    name=function.get("name") or "",
                    arguments=function.get("arguments") or "",
                )
            )

        if message.get("tool_call_id"):
            lines.append(f"tool_call_id={message['tool_call_id']}")
        lines.append("")
    return "\n".join(lines).strip()


def _message_search_text(message: Dict[str, Any]) -> str:
    """把一条消息的所有可检索字段拼成一段文本。"""
    parts: List[str] = [str(message.get("role") or "")]
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))
    for call in message.get("tool_calls") or []:
        function = (call or {}).get("function") or {}
        parts.append(str(function.get("name") or ""))
        parts.append(str(function.get("arguments") or ""))
    if message.get("tool_call_id"):
        parts.append(str(message["tool_call_id"]))
    return "\n".join(parts)


def _build_snippet(message: Dict[str, Any], terms: List[str]) -> str:
    """截取命中位置附近的原文片段。"""
    content = message.get("content")
    text = (
        content
        if isinstance(content, str) and content
        else _message_search_text(message)
    )
    # 内容命中不到关键词时（例如只命中工具参数），退回整条消息的可检索文本
    if not any(term in text.lower() for term in terms):
        text = _message_search_text(message)
    if not text:
        text = json.dumps(message, ensure_ascii=False)

    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    position = min(positions) if positions else 0

    start = max(0, position - MAX_SNIPPET_CHARS // 3)
    end = min(len(text), start + MAX_SNIPPET_CHARS)
    snippet = text[start:end].replace("\r", " ").replace("\n", " ")
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


class ContextArchiveStore:
    """负责 ``.agents/context/`` 下的归档写入与关键词检索。"""

    def __init__(self, project_root: Optional[Union[str, Path]] = None):
        self._project_root = (
            Path(project_root) if project_root is not None else Path(os.getcwd())
        )

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def context_dir(self) -> Path:
        return self._project_root / CONTEXT_ARCHIVE_DIR

    # ------------------------------------------------------------------ 写入
    def _next_archive_id(self) -> str:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = base
        index = 1
        while (self.context_dir / f"{candidate}.jsonl").exists():
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def save(self, messages: Sequence[Dict[str, Any]]) -> ArchiveInfo:
        """逐行保存原始消息；失败时抛异常，由调用方保留原上下文。"""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        archive_id = self._next_archive_id()
        target = self.context_dir / f"{archive_id}.jsonl"

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{archive_id}-",
            suffix=".tmp",
            dir=str(self.context_dir),
        )
        count = 0
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for message in messages:
                    handle.write(json.dumps(message, ensure_ascii=False))
                    handle.write("\n")
                    count += 1
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        return ArchiveInfo(
            id=archive_id,
            path=target,
            message_count=count,
        )

    # ------------------------------------------------------------------ 检索
    def _resolve_files(self, archive_id: Optional[str]):
        if archive_id:
            value = str(archive_id).strip()
            if not _ARCHIVE_ID_PATTERN.fullmatch(value):
                return None, {"success": False, "error": f"归档编号格式无效：{archive_id}"}
            path = self.context_dir / f"{value}.jsonl"
            if not path.is_file():
                return None, {
                    "success": False,
                    "error": f"未找到编号为 {value} 的上下文归档",
                }
            return [path], None

        if not self.context_dir.is_dir():
            return [], None
        # 归档文件名即时间戳，倒序保证新记录优先
        return sorted(self.context_dir.glob("*.jsonl"), key=lambda p: p.name, reverse=True), None

    def search(self, text: str, archive_id: Optional[str] = None) -> Dict[str, Any]:
        """在指定或全部归档中做本地全文关键词检索。"""
        query = (text or "").strip()
        if not query:
            return {"success": False, "error": "检索内容不能为空"}

        terms = [term for term in query.lower().split() if term]
        if not terms:
            return {"success": False, "error": "检索内容不能为空"}

        files, error = self._resolve_files(archive_id)
        if error is not None:
            return error

        matches: List[Dict[str, Any]] = []
        errors: List[str] = []
        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            message = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(message, dict):
                            continue

                        haystack = _message_search_text(message).lower()
                        if not all(term in haystack for term in terms):
                            continue
                        score = sum(haystack.count(term) for term in terms)
                        matches.append(
                            {
                                "archive_id": path.stem,
                                "line": line_number,
                                "role": message.get("role") or "unknown",
                                "score": score,
                                "snippet": _build_snippet(message, terms),
                            }
                        )
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{path.name}: {exc}")

        # 命中次数多的优先；同分时保持归档文件的倒序（新归档在前）
        matches.sort(key=lambda item: -item["score"])

        total_matches = len(matches)
        selected: List[Dict[str, Any]] = []
        budget = MAX_RECALL_TOTAL_CHARS
        for match in matches[:MAX_RECALL_RESULTS]:
            if budget <= 0:
                break
            snippet = match["snippet"]
            if len(snippet) > budget:
                snippet = snippet[: max(0, budget - 1)] + "…"
            match = {**match, "snippet": snippet}
            selected.append(match)
            budget -= len(snippet)

        result: Dict[str, Any] = {
            "query": query,
            "archive_id": archive_id or "all",
            "archive_count": len(files),
            "total_matches": total_matches,
            "returned": len(selected),
            "truncated": len(selected) < total_matches,
            "matches": selected,
        }
        if errors:
            result["errors"] = errors
        if not selected:
            result["message"] = (
                "未找到匹配的历史内容，可尝试更换关键词或指定归档编号"
            )
        return {"success": True, "result": result}


# ---------------------------------------------------------------- 当前归档目录
_active_store: Optional[ContextArchiveStore] = None


def set_active_context_store(store: Optional[ContextArchiveStore]) -> None:
    """设置当前进程内 recallContext 使用的归档目录。"""
    global _active_store
    _active_store = store


def get_active_context_store() -> ContextArchiveStore:
    """获取当前归档目录；尚未设置时按当前工作目录惰性创建。"""
    global _active_store
    if _active_store is None:
        _active_store = ContextArchiveStore()
    return _active_store


# ---------------------------------------------------------------- 上下文管理器
class ContextManager:
    """组合 Token 统计、窗口配置与归档存储。"""

    def __init__(
        self,
        project_root: Optional[Union[str, Path]] = None,
        context_window: Optional[int] = None,
        threshold: float = DEFAULT_COMPACT_THRESHOLD,
        summary_target: int = DEFAULT_SUMMARY_TOKENS,
    ):
        self._project_root = (
            Path(project_root) if project_root is not None else Path(os.getcwd())
        )
        self._context_window = self._parse_window(context_window)
        self._window_is_default = self._context_window is None
        if self._context_window is None:
            self._context_window = DEFAULT_CONTEXT_WINDOW
        self._threshold = float(threshold)
        self._summary_target = int(summary_target)
        self._api_tokens: Optional[int] = None
        self._store = ContextArchiveStore(self._project_root)

    @staticmethod
    def _parse_window(value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    # ------------------------------------------------------------------ 属性
    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def window_is_default(self) -> bool:
        return self._window_is_default

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def summary_target(self) -> int:
        return self._summary_target

    @property
    def archive_store(self) -> ContextArchiveStore:
        return self._store

    # ------------------------------------------------------------------ 统计
    def estimate(
        self,
        messages: Sequence[Dict[str, Any]],
        system_prompt: str = "",
        tools: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> int:
        return (
            estimate_tokens(system_prompt)
            + estimate_messages_tokens(messages)
            + estimate_tools_tokens(tools)
        )

    def record_api_usage(self, usage: Optional[Dict[str, Any]]) -> None:
        """记录模型 API 返回的 usage；无效或缺失时清空，回退到估算。"""
        if not isinstance(usage, dict):
            self._api_tokens = None
            return
        total = usage.get("total_tokens")
        if not total:
            prompt = usage.get("prompt_tokens") or 0
            completion = usage.get("completion_tokens") or 0
            total = prompt + completion
        try:
            value = int(total)
        except (TypeError, ValueError):
            value = 0
        self._api_tokens = value if value > 0 else None

    def reset_usage(self) -> None:
        """上下文被改写（追加工具结果、压缩替换）后清除 API 统计。"""
        self._api_tokens = None

    def usage(
        self,
        messages: Sequence[Dict[str, Any]],
        system_prompt: str = "",
        tools: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> ContextUsage:
        if self._api_tokens is not None:
            tokens = self._api_tokens
            source = "api"
        else:
            tokens = self.estimate(messages, system_prompt, tools)
            source = "estimate"
        return ContextUsage(
            tokens=max(0, int(tokens)),
            window=self._context_window,
            threshold=self._threshold,
            window_is_default=self._window_is_default,
            source=source,
        )

    # ------------------------------------------------------------------ 归档
    def save_archive(self, messages: Sequence[Dict[str, Any]]) -> ArchiveInfo:
        return self._store.save(messages)
