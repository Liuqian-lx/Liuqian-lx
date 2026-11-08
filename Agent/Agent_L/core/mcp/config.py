"""MCP 服务器配置读取。

以程序启动时的工作目录（os.getcwd()）为根读取 .mcp.json，兼容标准 MCP
客户端格式：

    {
      "mcpServers": {
        "server-name": {
          "type": "streamable_http",   # 或 "stdio"
          "url": "https://host/mcp"     # streamable_http 必填
          # stdio 使用 command / args / env / cwd
        }
      }
    }

容错约定：
- 配置文件不存在 → 静默返回空列表；
- JSON 格式错误 / 顶层结构错误 → 返回空列表，并把原因记录到 MCPConfigLoadResult.errors；
- 单条服务器配置字段缺失或类型不支持 → 跳过该条，其余服务器照常加载。

本模块不打印任何内容、不抛异常，所有问题都通过返回值表达。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

MCP_CONFIG_FILE = ".mcp.json"
MCP_SERVERS_KEY = "mcpServers"

PROTOCOL_STDIO = "stdio"
PROTOCOL_STREAMABLE_HTTP = "streamable_http"
SUPPORTED_PROTOCOLS = (PROTOCOL_STDIO, PROTOCOL_STREAMABLE_HTTP)

# 兼容常见写法，统一归一化为内部协议名
_PROTOCOL_ALIASES = {
    "stdio": PROTOCOL_STDIO,
    "streamable_http": PROTOCOL_STREAMABLE_HTTP,
    "streamable-http": PROTOCOL_STREAMABLE_HTTP,
    "streamablehttp": PROTOCOL_STREAMABLE_HTTP,
    "http": PROTOCOL_STREAMABLE_HTTP,
}


@dataclass
class MCPServerConfig:
    """单个 MCP 服务器的连接配置。"""

    name: str
    type: str
    url: str = ""
    command: str = ""
    args: Tuple[str, ...] = ()
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class MCPConfigLoadResult:
    """配置加载结果：可用的服务器 + 被跳过条目的原因。"""

    path: Optional[Path] = None
    servers: List[MCPServerConfig] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def default_config_path(base_dir: Optional[Union[str, Path]] = None) -> Path:
    """返回 .mcp.json 的读取路径，默认以程序启动时的工作目录为根。"""
    root = Path(base_dir) if base_dir is not None else Path(os.getcwd())
    return root / MCP_CONFIG_FILE


def load_mcp_config(
    config_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Union[str, Path]] = None,
) -> MCPConfigLoadResult:
    """读取并校验 MCP 配置。

    config_path 优先；未提供时使用 base_dir（默认 os.getcwd()）下的 .mcp.json。
    """
    path = Path(config_path) if config_path is not None else default_config_path(base_dir)
    result = MCPConfigLoadResult(path=path)

    try:
        if not path.is_file():
            return result
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        result.errors.append(f"读取 MCP 配置文件失败：{exc}")
        return result

    try:
        data = json.loads(raw_text)
    except (ValueError, TypeError) as exc:
        result.errors.append(f"MCP 配置文件格式错误：{exc}")
        return result

    if not isinstance(data, dict):
        result.errors.append("MCP 配置文件格式错误：顶层必须是 JSON 对象")
        return result

    servers = data.get(MCP_SERVERS_KEY)
    if servers is None:
        return result
    if not isinstance(servers, dict):
        result.errors.append(f"MCP 配置字段 {MCP_SERVERS_KEY} 必须是对象")
        return result

    for name, raw in servers.items():
        server = _parse_server(name, raw, result.errors)
        if server is not None:
            result.servers.append(server)

    return result


def load_mcp_server_configs(
    config_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Union[str, Path]] = None,
) -> List[MCPServerConfig]:
    """只返回可用的服务器配置列表（兼容只需列表的调用方）。"""
    return load_mcp_config(config_path=config_path, base_dir=base_dir).servers


def _parse_server(
    name: Any,
    raw: Any,
    errors: List[str],
) -> Optional[MCPServerConfig]:
    if not isinstance(name, str) or not name.strip():
        errors.append("MCP 配置中存在空的服务器名，已跳过")
        return None
    server_name = name.strip()

    if not isinstance(raw, Mapping):
        errors.append(f"MCP 服务器「{server_name}」配置不是 JSON 对象，已跳过")
        return None

    protocol = _normalize_protocol(raw.get("type"), raw)
    if protocol is None:
        errors.append(
            f"MCP 服务器「{server_name}」缺少受支持的 type"
            f"（{', '.join(SUPPORTED_PROTOCOLS)}），已跳过"
        )
        return None

    if protocol == PROTOCOL_STREAMABLE_HTTP:
        url = _text(raw.get("url")).strip()
        if not url:
            errors.append(f"MCP 服务器「{server_name}」缺少 url，已跳过")
            return None
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"MCP 服务器「{server_name}」的 url 不是合法的 HTTP 地址，已跳过")
            return None
        return MCPServerConfig(
            name=server_name,
            type=protocol,
            url=url,
            headers=_text_map(raw.get("headers")),
        )

    command = _text(raw.get("command")).strip()
    if not command:
        errors.append(f"MCP 服务器「{server_name}」缺少 command，已跳过")
        return None
    return MCPServerConfig(
        name=server_name,
        type=protocol,
        command=command,
        args=_text_tuple(raw.get("args")),
        env=_text_map(raw.get("env")),
        cwd=_text(raw.get("cwd")).strip(),
    )


def _normalize_protocol(value: Any, raw: Mapping[str, Any]) -> Optional[str]:
    """归一化协议名；type 缺失时按已有字段推断（command → stdio，url → http）。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        if _text(raw.get("command")).strip():
            return PROTOCOL_STDIO
        if _text(raw.get("url")).strip():
            return PROTOCOL_STREAMABLE_HTTP
        return None

    token = _text(value).strip().lower()
    return _PROTOCOL_ALIASES.get(token)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _text_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_text(item) for item in value)


def _text_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _text(item) for key, item in value.items()}
