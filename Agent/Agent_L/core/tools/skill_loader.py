"""动态技能加载工具：loadSkill。

大模型在 system prompt 中看到已发现的 Skill 名称与描述后，按需调用本工具
读取 SKILL.md 全文或 Skill 目录内的附件文件。

安全沙箱：
- 所有路径先经 os.path.realpath 规范化；
- 最终读取路径必须落在对应 Skill 目录内部；
- 绝对路径、相对路径与按文件名递归搜索三种方式都执行同一边界校验，
  禁止通过 ``../`` 或符号链接读取 Skill 目录之外的文件。

所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。
本模块不包含任何界面代码。
"""

from __future__ import annotations

import os
from typing import List, Optional

from ..skills import SKILL_FILE, SkillMeta, get_active_manager

OUTSIDE_SKILL_DIR_ERROR = "路径超出 Skill 目录范围，禁止访问"
MULTI_MATCH_HINT = "存在多个匹配文件，请指定完整路径"
FILE_NOT_FOUND_TEMPLATE = "Skill 中未找到指定文件：{}"
SKILL_NOT_FOUND_TEMPLATE = "未找到指定的 Skill：{}"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "loadSkill",
            "description": (
                "加载指定 Skill 的完整内容。当任务与 system prompt 中列出的某个 Skill "
                "描述匹配时调用。只传 name 时读取该 Skill 的 SKILL.md 全文；"
                "传入 filename 时可读取该 Skill 目录内的附件文件，"
                "filename 可以是相对路径、绝对路径或文件名。"
                "按文件名匹配到多个文件时会返回候选路径列表，此时请改用完整路径再次调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的 Skill 名称，必须与 system prompt 中列出的名称一致",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "可选，要加载的 Skill 附件文件路径或名称；"
                            "不传时读取该 Skill 的 SKILL.md 全文"
                        ),
                    },
                },
                "required": ["name"],
            },
        },
    },
]


def loadSkill(name="", filename=None) -> dict:
    """读取指定 Skill 的 SKILL.md 或附件文件。"""
    try:
        skill_name = _normalize_text(name)
        if not skill_name:
            return {"success": False, "error": "Skill 名称不能为空"}

        meta = get_active_manager().get(skill_name)
        if meta is None:
            return {
                "success": False,
                "error": SKILL_NOT_FOUND_TEMPLATE.format(skill_name),
            }

        skill_dir = os.path.realpath(str(meta.directory))
        target = _normalize_text(filename)

        if not target:
            return _read_skill_file(
                meta,
                os.path.join(skill_dir, SKILL_FILE),
                SKILL_FILE,
            )

        return _load_attachment(meta, skill_dir, target)
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"加载 Skill 失败：{exc}"}


def _load_attachment(meta: SkillMeta, skill_dir: str, filename: str) -> dict:
    """按「绝对路径 -> 相对路径 -> 仅文件名递归搜索」的顺序解析附件。"""
    if os.path.isabs(filename):
        # 绝对路径：先规范化，再校验是否落在 Skill 目录内部
        resolved = os.path.realpath(filename)
        if not _is_inside(skill_dir, resolved):
            return _outside_error()
        return _read_resolved(meta, skill_dir, resolved, filename)

    if _has_path_separator(filename):
        # 相对于 Skill 目录的路径：直接拼接后校验，阻止 ../ 穿越
        resolved = os.path.realpath(os.path.join(skill_dir, filename))
        if not _is_inside(skill_dir, resolved):
            return _outside_error()
        return _read_resolved(meta, skill_dir, resolved, filename)

    # 仅文件名：在 Skill 目录内递归搜索
    matches = _search_by_name(skill_dir, filename)
    if not matches:
        return {
            "success": False,
            "error": FILE_NOT_FOUND_TEMPLATE.format(filename),
        }
    if len(matches) > 1:
        return {
            "success": True,
            "result": {
                "skill_name": meta.name,
                "matches": matches,
                "hint": MULTI_MATCH_HINT,
            },
        }
    return _read_resolved(meta, skill_dir, matches[0], filename)


def _read_resolved(
    meta: SkillMeta,
    skill_dir: str,
    resolved: str,
    fallback_label: str,
) -> dict:
    """校验目标为 Skill 目录内的文件后读取。"""
    if not _is_inside(skill_dir, resolved):
        return _outside_error()
    if not os.path.exists(resolved):
        return {
            "success": False,
            "error": FILE_NOT_FOUND_TEMPLATE.format(fallback_label),
        }
    if not os.path.isfile(resolved):
        return {
            "success": False,
            "error": f"指定的路径不是文件：{fallback_label}",
        }

    label = _relative_label(skill_dir, resolved) or fallback_label
    return _read_skill_file(meta, resolved, label)


def _read_skill_file(meta: SkillMeta, path: str, label: str) -> dict:
    """以 UTF-8 读取文件，返回统一格式的结果。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except FileNotFoundError:
        return {
            "success": False,
            "error": FILE_NOT_FOUND_TEMPLATE.format(label),
        }
    except IsADirectoryError:
        return {
            "success": False,
            "error": f"指定的路径不是文件：{label}",
        }
    except UnicodeDecodeError:
        return {
            "success": False,
            "error": f"文件编码错误，无法按 UTF-8 读取：{label}",
        }
    except OSError as exc:
        return {"success": False, "error": f"读取文件失败：{exc}"}

    return {
        "success": True,
        "result": {
            "skill_name": meta.name,
            "file": label,
            "content": content,
        },
    }


def _search_by_name(skill_dir: str, filename: str) -> List[str]:
    """在 Skill 目录内递归查找同名文件，返回 Skill 目录内的绝对路径列表。"""
    matches: List[str] = []
    seen = set()

    for current, dirnames, filenames in os.walk(skill_dir, followlinks=False):
        # 不进入符号链接目录，避免绕过沙箱边界
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not os.path.islink(os.path.join(current, name))
        )
        for candidate in sorted(filenames):
            if not _same_filename(candidate, filename):
                continue
            resolved = os.path.realpath(os.path.join(current, candidate))
            if not _is_inside(skill_dir, resolved):
                continue
            if not os.path.isfile(resolved) or resolved in seen:
                continue
            seen.add(resolved)
            matches.append(resolved)

    return matches


def _same_filename(candidate: str, wanted: str) -> bool:
    """比较文件名；Windows 文件系统不区分大小写。"""
    if candidate == wanted:
        return True
    return os.name == "nt" and candidate.lower() == wanted.lower()


def _is_inside(skill_dir: str, target: str) -> bool:
    """判断规范化后的 target 是否位于 skill_dir 内部（含目录本身）。"""
    try:
        base = os.path.normcase(os.path.realpath(skill_dir))
        candidate = os.path.normcase(os.path.realpath(target))
        return os.path.commonpath([base, candidate]) == base
    except (ValueError, OSError):
        # 不同盘符或非法路径一律视为越界
        return False


def _has_path_separator(value: str) -> bool:
    if "/" in value or "\\" in value:
        return True
    return bool(os.altsep) and os.altsep in value


def _relative_label(skill_dir: str, path: str) -> str:
    """返回相对于 Skill 目录的展示路径，统一使用正斜杠。"""
    try:
        relative = os.path.relpath(path, skill_dir)
    except ValueError:
        return ""
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return ""
    return relative.replace(os.sep, "/")


def _normalize_text(value: Optional[object]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _outside_error() -> dict:
    return {"success": False, "error": OUTSIDE_SKILL_DIR_ERROR}


TOOL_MAP = {
    "loadSkill": loadSkill,
}
