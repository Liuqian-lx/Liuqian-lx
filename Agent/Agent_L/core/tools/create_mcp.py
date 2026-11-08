"""MCP 配置管理工具：createMCP。

大模型可根据用户提供的服务器信息，把配置写入**当前工作目录**的
``.mcp.json``，并立即重载 MCP 管理器，使新服务器的工具无需重启程序即可
出现在工具列表中。

支持的能力：
- 新增服务器；同名服务器直接覆盖更新；
- ``streamable_http``（需要 url）与 ``stdio``（需要 command）两种协议；
- 保留配置文件中其他已有服务器，不破坏原有配置。

安全规则：
- 服务器名称仅允许 ASCII 字母、数字、点、下划线和连字符，且以字母或
  数字开头，长度 1-64；
- 只写当前工作目录下的 ``.mcp.json``；若该文件是符号链接且指向工作目录
  之外，直接拒绝；
- 已有配置文件不是合法 JSON 或结构错误时拒绝覆盖，避免损坏用户配置；
- 写入采用「临时文件 + 原子替换」，写入失败不会留下半个文件。

所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。
本模块不包含任何界面代码。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

MCP_CONFIG_FILE = ".mcp.json"
MCP_SERVERS_KEY = "mcpServers"

PROTOCOL_STDIO = "stdio"
PROTOCOL_STREAMABLE_HTTP = "streamable_http"

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_TYPE_ALIASES = {
    "stdio": PROTOCOL_STDIO,
    "streamable_http": PROTOCOL_STREAMABLE_HTTP,
    "streamable-http": PROTOCOL_STREAMABLE_HTTP,
    "streamablehttp": PROTOCOL_STREAMABLE_HTTP,
    "http": PROTOCOL_STREAMABLE_HTTP,
}

INVALID_NAME_ERROR = (
    "MCP 服务器名称不合法：仅允许字母、数字、点、下划线和连字符，"
    "需以字母或数字开头，长度 1-64"
)
INVALID_TYPE_ERROR = "MCP 协议类型不合法，仅支持 streamable_http 或 stdio"
INVALID_URL_ERROR = "streamable_http 类型需要合法的 url（以 http:// 或 https:// 开头）"
MISSING_COMMAND_ERROR = "stdio 类型需要提供 command（可执行程序路径）"
INVALID_ARGS_ERROR = "args 必须是字符串数组"
INVALID_ENV_ERROR = "env 必须是字符串到字符串的对象"
INVALID_HEADERS_ERROR = "headers 必须是字符串到字符串的对象"
READ_CONFIG_ERROR = "读取现有 {} 失败：{}"
INVALID_CONFIG_ERROR = "现有 {} 格式错误，已拒绝覆盖：{}"
OUTSIDE_CWD_ERROR = "配置路径超出当前工作目录范围，禁止写入"
WRITE_CONFIG_ERROR = "写入 {} 失败：{}"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "createMCP",
            "description": (
                "新增或更新 MCP 服务器配置，写入当前工作目录的 .mcp.json，"
                "并立即重载 MCP 管理器，新服务器的工具无需重启即可使用。"
                "name 为服务器名（字母、数字、点、下划线、连字符）；type 支持 "
                "streamable_http（需 url）与 stdio（需 command，可通过 url 传空串）；"
                "url 为 MCP 服务地址。同名服务器会被覆盖更新，其他服务器保持不变。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "MCP 服务器名称，例如 PetHospitalMCP",
                    },
                    "type": {
                        "type": "string",
                        "description": "协议类型：streamable_http 或 stdio",
                        "enum": ["streamable_http", "stdio"],
                    },
                    "url": {
                        "type": "string",
                        "description": (
                            "MCP 服务地址，例如 http://127.0.0.1:8091/mcp；"
                            "stdio 类型可传空字符串"
                        ),
                    },
                    "command": {
                        "type": "string",
                        "description": "stdio 类型的可执行程序，例如 python",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "stdio 类型的程序参数列表",
                    },
                    "env": {
                        "type": "object",
                        "description": "stdio 类型的环境变量",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "stdio 类型的工作目录",
                    },
                    "headers": {
                        "type": "object",
                        "description": "streamable_http 类型的请求头",
                    },
                },
                "required": ["name", "type", "url"],
            },
        },
    },
]


def createMCP(
    name: str = "",
    type: str = "",
    url: str = "",
    command: str = "",
    args: Optional[Any] = None,
    env: Optional[Any] = None,
    cwd: str = "",
    headers: Optional[Any] = None,
) -> dict:
    """新增或覆盖 MCP 服务器配置，并热重载 MCP 工具。"""
    try:
        server_name = _normalize_text(name)
        if not server_name or not NAME_PATTERN.match(server_name):
            return {"success": False, "error": INVALID_NAME_ERROR}

        protocol = _normalize_type(type)
        if protocol is None:
            return {"success": False, "error": INVALID_TYPE_ERROR}

        entry = _build_entry(
            protocol=protocol,
            url=url,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            headers=headers,
        )
        if "error" in entry:
            return {"success": False, "error": entry["error"]}

        config_path, error = _resolve_config_path()
        if error:
            return {"success": False, "error": error}

        loaded, error = _load_config(config_path)
        if error:
            return {"success": False, "error": error}
        data, servers = loaded
        action = "updated" if server_name in servers else "created"
        servers[server_name] = entry["config"]

        try:
            _write_config(config_path, data)
        except OSError as exc:
            return {
                "success": False,
                "error": WRITE_CONFIG_ERROR.format(MCP_CONFIG_FILE, exc),
            }

        # 配置落盘后立即重载，保证新工具在下一轮模型请求中可用
        reload_warning = ""
        mcp_tools: list = []
        mcp_errors: list = []
        try:
            from . import refresh_mcp_tools

            mcp_tools, mcp_errors = refresh_mcp_tools()
        except Exception as exc:  # 兜底：配置已写入，但热重载失败
            reload_warning = f"配置已写入，但刷新 MCP 管理器失败：{exc}"

        result: Dict[str, Any] = {
            "name": server_name,
            "type": protocol,
            "config_path": str(config_path),
            "action": action,
            "mcp_tool_count": len(mcp_tools),
            "mcp_tools": [
                item["function"]["name"]
                for item in mcp_tools
                if isinstance(item, dict)
                and isinstance(item.get("function"), dict)
            ],
            "mcp_errors": mcp_errors,
            "message": (
                f"MCP 服务器 {server_name} 配置已{'更新' if action == 'updated' else '新增'}"
                "并已重载工具列表"
            ),
        }
        if isinstance(entry["config"].get("url"), str):
            result["url"] = entry["config"]["url"]
        if reload_warning:
            result["warning"] = reload_warning
        return {"success": True, "result": result}
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"创建 MCP 配置失败：{exc}"}


# ------------------------------------------------------------------ 参数处理
def _normalize_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_type(value: Any) -> Optional[str]:
    token = _normalize_text(value).lower()
    return _TYPE_ALIASES.get(token)


def _build_entry(
    protocol: str,
    url: Any,
    command: Any,
    args: Any,
    env: Any,
    cwd: Any,
    headers: Any,
) -> Dict[str, Any]:
    """构造成标准 mcpServers 条目；校验失败返回 {"error": ...}。"""
    config: Dict[str, Any] = {"type": protocol}

    if protocol == PROTOCOL_STREAMABLE_HTTP:
        address = _normalize_text(url)
        parsed = urlparse(address)
        if not address or parsed.scheme not in ("http", "https") or not parsed.netloc:
            return {"error": INVALID_URL_ERROR}
        config["url"] = address

        header_map = _text_map(headers)
        if header_map is None:
            return {"error": INVALID_HEADERS_ERROR}
        if header_map:
            config["headers"] = header_map
        return {"config": config}

    program = _normalize_text(command)
    if not program:
        return {"error": MISSING_COMMAND_ERROR}
    config["command"] = program

    arg_list = _text_list(args)
    if arg_list is None:
        return {"error": INVALID_ARGS_ERROR}
    if arg_list:
        config["args"] = arg_list

    env_map = _text_map(env)
    if env_map is None:
        return {"error": INVALID_ENV_ERROR}
    if env_map:
        config["env"] = env_map

    workdir = _normalize_text(cwd)
    if workdir:
        config["cwd"] = workdir
    return {"config": config}


def _text_list(value: Any) -> Optional[list]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return None
    return [item if isinstance(item, str) else str(item) for item in value]


def _text_map(value: Any) -> Optional[Dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    return {str(key): item if isinstance(item, str) else str(item) for key, item in value.items()}


# ------------------------------------------------------------------ 文件读写
def _resolve_config_path() -> tuple[Path, str]:
    """返回 <cwd>/.mcp.json，并确保真实路径仍在工作目录内。"""
    cwd_real = os.path.realpath(os.getcwd())
    config_path = Path(cwd_real) / MCP_CONFIG_FILE
    target_real = os.path.realpath(config_path)
    try:
        if os.path.commonpath([cwd_real, target_real]) != cwd_real:
            return config_path, OUTSIDE_CWD_ERROR
    except (OSError, ValueError):
        return config_path, OUTSIDE_CWD_ERROR
    return config_path, ""


def _load_config(config_path: Path) -> tuple[tuple[Dict[str, Any], Dict[str, Any]], str]:
    """读取现有配置；返回 ((完整数据, mcpServers), 错误信息)。"""
    if not config_path.exists():
        servers: Dict[str, Any] = {}
        return ({MCP_SERVERS_KEY: servers}, servers), ""

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ({}, {}), READ_CONFIG_ERROR.format(MCP_CONFIG_FILE, exc)

    try:
        data = json.loads(raw_text) if raw_text.strip() else {}
    except (ValueError, TypeError) as exc:
        return ({}, {}), INVALID_CONFIG_ERROR.format(MCP_CONFIG_FILE, exc)

    if not isinstance(data, dict):
        return ({}, {}), INVALID_CONFIG_ERROR.format(
            MCP_CONFIG_FILE, "顶层必须是 JSON 对象"
        )

    servers = data.get(MCP_SERVERS_KEY)
    if servers is None:
        servers = {}
        data[MCP_SERVERS_KEY] = servers
    if not isinstance(servers, dict):
        return ({}, {}), INVALID_CONFIG_ERROR.format(
            MCP_CONFIG_FILE, f"{MCP_SERVERS_KEY} 必须是对象"
        )
    return (data, servers), ""


def _write_config(config_path: Path, data: Dict[str, Any]) -> None:
    """临时文件 + 原子替换，保证配置要么完整写入、要么保持原样。"""
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    directory = str(config_path.parent)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{MCP_CONFIG_FILE}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, config_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


TOOL_MAP = {
    "createMCP": createMCP,
}
