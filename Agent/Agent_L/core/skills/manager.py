"""Skill 生命周期管理。

职责：
- 在 Agent 初始化时扫描 ``<项目根>/.agents/skills/`` 并缓存元数据；
- 按名称查找 Skill；
- 生成注入 system prompt 的 Skill 列表段落；
- 维护当前进程内生效的 SkillManager（供 loadSkill 工具读取）。

Skill 全文不会在初始化阶段载入，只有大模型调用 ``loadSkill`` 时才读取。
本模块只使用 Python 标准库，不输出到终端。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Union

from .loader import SkillMeta, discover_skills, get_skills_root

PathLike = Union[str, Path]

SKILLS_PROMPT_HEADER = "## 可用 Skills"
SKILLS_PROMPT_INTRO = (
    "当前项目发现以下 Skill。Skill 的完整内容不会预先载入上下文，"
    "当用户任务与某个 Skill 的描述匹配时，请调用 loadSkill 工具加载详细内容。"
    "只传 name 会读取该 Skill 的 SKILL.md 全文；需要附件时再传 filename 指定文件。"
)


class SkillManager:
    """管理一次 Agent 运行期间发现的 Skill。"""

    def __init__(self, project_root: Optional[PathLike] = None):
        # 以构造时的当前工作目录作为项目根，捕获程序启动位置
        self._project_root = (
            Path(project_root) if project_root is not None else Path(os.getcwd())
        )
        self._skills: Dict[str, SkillMeta] = {}
        self._errors: List[str] = []
        self.reload()

    # ------------------------------------------------------------------ 属性
    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def skills_root(self) -> Path:
        return get_skills_root(self._project_root)

    @property
    def skills(self) -> List[SkillMeta]:
        """已发现的 Skill 列表（按扫描顺序，去重后）。"""
        return list(self._skills.values())

    @property
    def names(self) -> List[str]:
        return list(self._skills.keys())

    @property
    def errors(self) -> List[str]:
        """扫描阶段被静默跳过的 Skill 及原因（供验证脚本检查）。"""
        return list(self._errors)

    def __len__(self) -> int:
        return len(self._skills)

    def __iter__(self) -> Iterator[SkillMeta]:
        return iter(self._skills.values())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._skills

    # ------------------------------------------------------------------ 管理
    def reload(self) -> None:
        """重新扫描 Skill 目录，覆盖当前缓存。"""
        found, errors = discover_skills(self._project_root)
        self._skills = {meta.name: meta for meta in found}
        self._errors = errors

    def get(self, name: str) -> Optional[SkillMeta]:
        """按名称查找 Skill，不存在时返回 None。"""
        if not isinstance(name, str):
            return None
        return self._skills.get(name.strip())

    # ------------------------------------------------------------------ Prompt
    def build_prompt_section(self) -> str:
        """生成追加到 system prompt 末尾的 Skill 列表；无 Skill 时返回空串。"""
        if not self._skills:
            return ""

        lines = [SKILLS_PROMPT_HEADER, "", SKILLS_PROMPT_INTRO, ""]
        for meta in self._skills.values():
            lines.append(f"- {meta.name}: {_single_line(meta.description)}")
        return "\n".join(lines)


def _single_line(text: str) -> str:
    """把多行描述压缩成一行，保证列表格式稳定。"""
    return " ".join(text.split())


# ---------------------------------------------------------------- 当前生效实例
_active_manager: Optional[SkillManager] = None


def set_active_manager(manager: Optional[SkillManager]) -> None:
    """设置当前进程内 loadSkill 使用的 SkillManager。"""
    global _active_manager
    _active_manager = manager


def get_active_manager() -> SkillManager:
    """获取当前 SkillManager；尚未设置时按当前工作目录惰性创建。"""
    global _active_manager
    if _active_manager is None:
        _active_manager = SkillManager()
    return _active_manager
