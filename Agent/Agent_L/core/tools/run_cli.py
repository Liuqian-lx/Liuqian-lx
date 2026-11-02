"""命令行执行工具：RunCli。

允许 Agent 调用本地已安装的任意 CLI 程序（如 python、git、dir、curl）。
程序名与参数始终以列表形式交给 subprocess 执行，不使用 shell，
因此参数中的空格、引号、重定向符号等不会被解释为 shell 语法。

所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。

安全说明（教学环境）：
- 本阶段按题目要求不实现命令白名单、黑名单或人工审批机制；
- 命令以运行 Agent 的当前用户权限执行，具备该用户的文件与网络访问能力；
- 仅适用于受控的教学实验环境，切勿在不可信输入或生产环境中直接开放。
"""

from __future__ import annotations

import locale
import subprocess
from typing import Any, List

TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 4000
TRUNCATE_MARKER = "\n...输出已截断"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "RunCli",
            "description": (
                "在本机执行已安装的命令行程序，例如 python、git、dir、curl。"
                "command 传程序名，args 传参数列表（逐项分开，不要拼接成一条命令字符串）；"
                "执行不经过 shell。返回退出码、标准输出和标准错误，"
                "单次执行超时 30 秒，stdout/stderr 各截断到前 4000 字符。"
                "即使命令以非 0 退出码结束也返回 success=true，请根据 exit_code 判断结果。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "可执行程序名称，例如 python、git、dir、curl",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "程序参数列表，每项一个字符串，默认为空数组",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


def run_cli(command="", args=None) -> dict:
    """执行本地命令行程序，返回命令名、参数、退出码与输出。"""
    try:
        if not isinstance(command, str) or not command.strip():
            return {"success": False, "error": "命令名称不能为空"}

        name = command.strip()
        arg_list = _normalize_args(args)
        if arg_list is None:
            return {"success": False, "error": "参数 args 必须是字符串数组"}

        # 程序名与参数拼装为列表执行，绝不经过 shell，避免命令注入
        argv = [name, *arg_list]

        try:
            completed = _run_process(argv)
        except FileNotFoundError:
            return {"success": False, "error": f"未找到命令：{name}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令执行超时（{TIMEOUT_SECONDS}秒）"}
        except OSError as exc:
            # 权限不足、可执行文件损坏等系统错误
            return {"success": False, "error": f"命令执行失败：{exc}"}

        return {
            "success": True,
            "result": {
                "command": name,
                "args": arg_list,
                "exit_code": completed.returncode,
                "stdout": _truncate(_decode_output(completed.stdout)),
                "stderr": _truncate(_decode_output(completed.stderr)),
            },
        }
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"命令执行失败：{exc}"}


def _normalize_args(args: Any) -> Any:
    """把 args 归一化为字符串列表；类型不合法时返回 None。"""
    if args is None:
        return []
    if isinstance(args, (list, tuple)):
        return [item if isinstance(item, str) else str(item) for item in args]
    return None


def _run_process(argv: List[str]) -> subprocess.CompletedProcess:
    """使用参数列表执行子进程，捕获输出并设置超时，绝不经过 shell。"""
    return subprocess.run(
        argv,
        capture_output=True,
        timeout=TIMEOUT_SECONDS,
        shell=False,
        check=False,
    )


def _decode_output(raw: Any) -> str:
    """把输出字节解码为文本：优先 UTF-8，其次系统本地编码。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw

    encodings = ["utf-8", locale.getpreferredencoding(False), "gb18030"]
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str) -> str:
    """输出超过 4000 字符时截断，并标注已截断，避免占用过多上下文 Token。"""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + TRUNCATE_MARKER


TOOL_MAP = {
    "RunCli": run_cli,
}
