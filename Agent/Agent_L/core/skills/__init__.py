"""Skill 能力：发现、元数据解析与生命周期管理。"""

from __future__ import annotations

from .loader import (
    SKILL_FILE,
    SkillMeta,
    discover_skills,
    get_skills_root,
    load_skill_metadata,
    parse_frontmatter,
    read_frontmatter,
    scan_skills,
)
from .manager import (
    SkillManager,
    get_active_manager,
    set_active_manager,
)

__all__ = [
    "SKILL_FILE",
    "SkillMeta",
    "SkillManager",
    "discover_skills",
    "get_skills_root",
    "load_skill_metadata",
    "parse_frontmatter",
    "read_frontmatter",
    "scan_skills",
    "get_active_manager",
    "set_active_manager",
]
