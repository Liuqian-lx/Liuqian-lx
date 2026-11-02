"""技能创建工具：createSkill。

大模型可根据自然语言把一段完整内容写成新的 Skill：本工具负责校验名称、
防止覆盖、限制写入路径，并把内容规范化为带 YAML Frontmatter 的 ``SKILL.md``，
保证创建结果一定能被现有的 SkillManager 扫描到。

安全规则：
- 名称仅允许小写字母、数字和连字符，且不能以连字符开头或结尾；
- 目标目录已存在时直接拒绝，绝不覆盖已有 Skill；
- 最终路径先经 ``os.path.realpath`` 规范化，必须落在
  ``<工作目录>/.agents/skills/`` 内部。

所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。
本模块不包含任何界面代码。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from ..skills import SKILL_FILE, get_active_manager
from ..skills.loader import FRONTMATTER_DELIMITER, SKILLS_DIR_NAME, SKILLS_SUBDIR

NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
DESCRIPTION_MAX_CHARS = 80

INVALID_NAME_ERROR = "Skill 名称不合法，仅允许小写字母、数字和连字符（kebab-case 格式）"
EXISTED_TEMPLATE = "Skill {} 已存在，禁止覆盖原有内容"
OUTSIDE_SKILL_DIR_ERROR = "路径超出 Skill 目录范围，禁止创建"
CREATE_DIR_TEMPLATE = "创建 Skill 目录失败：{}"
WRITE_FILE_TEMPLATE = "写入 SKILL.md 失败：{}"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "createSkill",
            "description": (
                "创建一个新的 Skill。当用户希望把某套方法、流程或知识固化为可复用的 "
                "Skill 时调用。name 必须是 kebab-case 名称（仅小写字母、数字和连字符，"
                "不能以连字符开头或结尾），skillContext 是写入 SKILL.md 的完整内容。"
                "缺少 YAML Frontmatter 时会自动生成 name 与 description 头部；"
                "已有 Frontmatter 时会补全缺失字段并把 name 修正为传入的名称。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill 名称，kebab-case 格式，例如 pdf-tools",
                    },
                    "skillContext": {
                        "type": "string",
                        "description": "需要写入 SKILL.md 的完整内容（可包含 YAML Frontmatter）",
                    },
                },
                "required": ["name", "skillContext"],
            },
        },
    },
]


def createSkill(name="", skillContext="") -> dict:
    """按名称与内容创建新的 Skill 目录和 SKILL.md。"""
    try:
        skill_name = _normalize_text(name)
        if not skill_name or not NAME_PATTERN.match(skill_name):
            return {"success": False, "error": INVALID_NAME_ERROR}

        context = _normalize_context(skillContext)

        # 以程序启动时的工作目录为根，与 SkillManager 的扫描路径保持一致
        skills_root = os.path.join(os.getcwd(), SKILLS_DIR_NAME, SKILLS_SUBDIR)
        target = os.path.join(skills_root, skill_name)

        # 存在性检查必须发生在任何写入之前，确保不会覆盖已有 Skill
        if os.path.exists(target):
            return {"success": False, "error": EXISTED_TEMPLATE.format(skill_name)}

        # 路径安全沙箱：realpath 规范化后必须仍在 Skill 根目录内部
        resolved_root = os.path.realpath(skills_root)
        resolved_target = os.path.realpath(target)
        if not _is_inside(resolved_root, resolved_target) or resolved_target == resolved_root:
            return {"success": False, "error": OUTSIDE_SKILL_DIR_ERROR}

        try:
            os.makedirs(resolved_target, exist_ok=False)
        except FileExistsError:
            return {"success": False, "error": EXISTED_TEMPLATE.format(skill_name)}
        except OSError as exc:
            return {"success": False, "error": CREATE_DIR_TEMPLATE.format(exc)}

        content = _build_skill_content(skill_name, context)
        skill_file = os.path.join(resolved_target, SKILL_FILE)
        try:
            with open(skill_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except OSError as exc:
            # 写入失败时回收本次新建的空目录，避免留下不可用的 Skill
            _cleanup_failed_creation(skill_file, resolved_target)
            return {"success": False, "error": WRITE_FILE_TEMPLATE.format(exc)}

        # 新建的 Skill 需要重新扫描后才能被 loadSkill 加载
        _refresh_active_manager(resolved_root)

        return {
            "success": True,
            "result": {
                "skill_name": skill_name,
                "skill_path": f"{SKILLS_DIR_NAME}/{SKILLS_SUBDIR}/{skill_name}",
                "file": SKILL_FILE,
                "message": "Skill 创建成功，已可被加载使用",
            },
        }
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"创建 Skill 失败：{exc}"}


# ------------------------------------------------------------------ 内容规范化
def _build_skill_content(name: str, context: str) -> str:
    """把用户内容规范化为带合法 Frontmatter 的 SKILL.md 全文。"""
    parsed = _split_frontmatter(context)
    if parsed is None:
        body = _clean_body(context)
        description = _summarize(body, name)
        return _render(name, description, body)

    header_lines, body_text = parsed
    body = _clean_body(body_text)
    description = _summarize(body, name)

    blocks = _parse_header_blocks(header_lines)
    has_name = False
    has_description = False
    rendered: List[str] = []

    for block in blocks:
        key = block["key"]
        if key == "name":
            # name 统一修正为标准名称，保证与目录名一致
            block["lines"] = [f"name: {name}"]
            has_name = True
        elif key == "description":
            if not _block_value(block):
                block["lines"] = [f"description: {_yaml_scalar(description)}"]
            has_description = True
        rendered.extend(block["lines"])

    if not has_name:
        rendered.insert(0, f"name: {name}")
    if not has_description:
        rendered.append(f"description: {_yaml_scalar(description)}")

    return _render_lines(rendered, body)


def _render(name: str, description: str, body: str) -> str:
    lines = [f"name: {name}", f"description: {_yaml_scalar(description)}"]
    return _render_lines(lines, body)


def _render_lines(header_lines: List[str], body: str) -> str:
    header = "\n".join([FRONTMATTER_DELIMITER, *header_lines, FRONTMATTER_DELIMITER])
    if body:
        return f"{header}\n\n{body}\n"
    return f"{header}\n"


def _split_frontmatter(text: str) -> Optional[Tuple[List[str], str]]:
    """拆分 Frontmatter；没有完整闭合的头部时返回 None。"""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIMITER:
            return lines[1:index], "\n".join(lines[index + 1 :])
    return None


def _parse_header_blocks(header_lines: List[str]) -> List[Dict[str, Any]]:
    """把 Frontmatter 行拆成「顶层键 + 其续行」的块，保留未知字段。"""
    blocks: List[Dict[str, Any]] = []
    for raw in header_lines:
        key = _top_level_key(raw)
        if key is not None:
            blocks.append({"key": key, "lines": [raw]})
        elif blocks:
            blocks[-1]["lines"].append(raw)
        else:
            # Frontmatter 开头的注释或空行，原样保留
            blocks.append({"key": None, "lines": [raw]})
    return blocks


def _top_level_key(raw: str) -> Optional[str]:
    """识别缩进为零的 ``key:`` 行，返回小写键名。"""
    if not raw or raw[0].isspace() or ":" not in raw:
        return None
    key, _, _ = raw.partition(":")
    key = key.strip()
    if not key or not all(ch.isalnum() or ch in "-_" for ch in key):
        return None
    return key.lower()


def _block_value(block: Dict[str, Any]) -> str:
    """提取块的字符串值，用于判断字段是否为空。"""
    first = block["lines"][0]
    _, _, value = first.partition(":")
    value = value.strip()
    if value in ("", "|", "|-", "|+", ">", ">-", ">+"):
        continuation = [line.strip() for line in block["lines"][1:] if line.strip()]
        return " ".join(continuation)
    return _strip_quotes(value)


def _strip_quotes(value: str) -> str:
    """去掉成对的单/双引号。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value.strip()


def _summarize(body: str, name: str) -> str:
    """截取正文前 80 字符作为 description；正文为空时给出兜底描述。"""
    compact = " ".join(body.split())
    if compact:
        return compact[:DESCRIPTION_MAX_CHARS]
    return f"{name} Skill"


def _yaml_scalar(value: str) -> str:
    """把摘要输出为安全的单行 YAML 标量，必要时使用双引号。"""
    text = " ".join(str(value).split())
    if not text:
        return '""'
    unsafe = (
        text[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in text
        or " #" in text
    )
    if unsafe:
        return json.dumps(text, ensure_ascii=False)
    return text


def _clean_body(text: str) -> str:
    """去掉 BOM 与首尾空白行，正文内部（含缩进）保持原样。"""
    lines = text.lstrip("\ufeff").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# ------------------------------------------------------------------ 辅助
def _refresh_active_manager(skills_root: str) -> None:
    """新建 Skill 后刷新当前 SkillManager 缓存，使其立即可被 loadSkill 读取。"""
    try:
        manager = get_active_manager()
        if os.path.normcase(os.path.realpath(str(manager.skills_root))) != os.path.normcase(
            os.path.realpath(skills_root)
        ):
            return
        manager.reload()
    except Exception:
        # 刷新失败不影响创建结果，下一次扫描仍会发现该 Skill
        pass


def _cleanup_failed_creation(skill_file: str, skill_dir: str) -> None:
    """写入失败时尽力回收本次创建的文件与空目录。"""
    try:
        if os.path.exists(skill_file):
            os.remove(skill_file)
        os.rmdir(skill_dir)
    except OSError:
        pass


def _is_inside(base_dir: str, target: str) -> bool:
    """判断规范化后的 target 是否位于 base_dir 内部（含目录本身）。"""
    try:
        base = os.path.normcase(os.path.realpath(base_dir))
        candidate = os.path.normcase(os.path.realpath(target))
        return os.path.commonpath([base, candidate]) == base
    except (ValueError, OSError):
        # 不同盘符或非法路径一律视为越界
        return False


def _normalize_text(value: Optional[object]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_context(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


TOOL_MAP = {
    "createSkill": createSkill,
}
