"""Skill 发现与元数据解析。

扫描规则：
- 以 ``<项目根>/.agents/skills/`` 为 Skill 根目录，根目录不存在时静默跳过；
- 每个一级子目录视为一个 Skill，必须包含 ``SKILL.md``；
- 只读取 ``SKILL.md`` 开头的 YAML Frontmatter，提取 ``name`` 与 ``description``；
  正文不读取，保证初始化阶段的开销最小。

本模块只使用 Python 标准库，不依赖任何界面代码，也不输出到终端。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

SKILLS_DIR_NAME = ".agents"
SKILLS_SUBDIR = "skills"
SKILL_FILE = "SKILL.md"
FRONTMATTER_DELIMITER = "---"
REQUIRED_FIELDS = ("name", "description")

PathLike = Union[str, Path]


@dataclass(frozen=True)
class SkillMeta:
    """一个已发现 Skill 的元数据（不含正文）。"""

    name: str
    description: str
    directory: Path


def get_skills_root(project_root: PathLike) -> Path:
    """返回项目根目录下约定的 Skill 根目录。"""
    return Path(project_root) / SKILLS_DIR_NAME / SKILLS_SUBDIR


def parse_frontmatter(text: str) -> Optional[Dict[str, str]]:
    """解析 ``---`` 包裹的 YAML Frontmatter。

    支持 ``key: value``、单双引号值以及 ``|`` / ``>`` 块标量。
    未找到完整 Frontmatter 时返回 None。
    """
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIMITER:
            return _parse_header_lines(lines[1:index])
    return None


def read_frontmatter(path: PathLike) -> Optional[Dict[str, str]]:
    """只读取文件头部的 Frontmatter，不读取正文。

    以二进制逐行读取，遇到结束分隔符立即返回；这样即使正文包含非法
    编码或体积很大，也不会影响元数据解析。
    """
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
            first_line = first.decode("utf-8-sig", errors="replace").strip()
            if first_line != FRONTMATTER_DELIMITER:
                return None

            header: List[str] = []
            for raw in handle:
                line = raw.decode("utf-8", errors="replace")
                if line.strip() == FRONTMATTER_DELIMITER:
                    return _parse_header_lines(header)
                header.append(line)
    except OSError:
        return None
    return None


def load_skill_metadata(skill_dir: PathLike) -> Tuple[Optional[SkillMeta], Optional[str]]:
    """读取单个 Skill 目录的元数据。

    返回值：
    - (SkillMeta, None)：解析成功；
    - (None, 错误说明)：目录缺少 SKILL.md 或 Frontmatter 不合法。
    """
    directory = Path(skill_dir)
    skill_file = directory / SKILL_FILE

    try:
        if not skill_file.is_file():
            return None, f"缺少 {SKILL_FILE}"
    except OSError as exc:
        return None, f"读取 {SKILL_FILE} 失败：{exc}"

    data = read_frontmatter(skill_file)
    if data is None:
        return None, f"{SKILL_FILE} 缺少有效的 YAML Frontmatter"

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name or not description:
        return None, "Frontmatter 缺少 name 或 description"

    return SkillMeta(name=name, description=description, directory=directory), None


def discover_skills(
    project_root: Optional[PathLike] = None,
) -> Tuple[List[SkillMeta], List[str]]:
    """以项目根目录为起点发现 Skill。

    project_root 为 None 时使用程序启动时的当前工作目录（os.getcwd()）。
    返回 (按目录名排序的 Skill 列表, 静默错误列表)。
    """
    root = Path(project_root) if project_root is not None else Path(os.getcwd())
    return scan_skills(get_skills_root(root))


def scan_skills(
    skills_directory: PathLike,
) -> Tuple[List[SkillMeta], List[str]]:
    """扫描指定的 Skill 目录，返回 (Skill 列表, 静默错误列表)。"""
    base = Path(skills_directory)
    skills: List[SkillMeta] = []
    errors: List[str] = []

    try:
        if not base.is_dir():
            # .agents/skills 不存在时静默跳过，不产生错误
            return skills, errors
        entries = sorted(base.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        errors.append(f"扫描 Skill 目录失败：{exc}")
        return skills, errors

    seen_names = set()
    for entry in entries:
        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue

        meta, error = load_skill_metadata(entry)
        if meta is None:
            errors.append(f"{entry.name}：{error}")
            continue
        if meta.name in seen_names:
            errors.append(f"{entry.name}：Skill 名称重复，已跳过：{meta.name}")
            continue

        seen_names.add(meta.name)
        skills.append(meta)

    return skills, errors


def _parse_header_lines(lines: Sequence[str]) -> Dict[str, str]:
    """解析 Frontmatter 内部的 key/value 行。"""
    result: Dict[str, str] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        index += 1

        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in raw:
            continue

        key, _, value = raw.partition(":")
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if value in ("|", "|-", "|+", ">", ">-", ">+"):
            folded = value.startswith(">")
            block, index = _read_block_scalar(lines, index, folded)
            result[key] = block
        else:
            result[key] = _strip_quotes(value)

    return result


def _read_block_scalar(
    lines: Sequence[str],
    start: int,
    folded: bool,
) -> Tuple[str, int]:
    """读取 ``|`` / ``>`` 块标量，返回 (文本, 下一行索引)。"""
    collected: List[str] = []
    indent: Optional[int] = None
    index = start

    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            collected.append("")
            index += 1
            continue

        current_indent = len(raw) - len(raw.lstrip())
        if indent is None:
            indent = current_indent
        if current_indent < indent:
            break

        collected.append(raw[indent:].rstrip())
        index += 1

    while collected and not collected[-1]:
        collected.pop()

    separator = " " if folded else "\n"
    return separator.join(collected).strip(), index


def _strip_quotes(value: str) -> str:
    """去掉成对的单/双引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value.strip()
