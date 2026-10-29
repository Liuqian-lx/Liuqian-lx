"""配置读取模块。

只负责解析 config.ini，不包含任何界面输出。配置缺失时抛出 ConfigError，
由调用方（入口或界面层）决定如何提示用户。
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Union

DEFAULT_CONFIG_FILE = "config.ini"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_FILE
CONFIG_SECTION = "llm"
SEARCH_SECTION = "search"
SEARCH_API_KEY_OPTION = "baidu_qianfan_api_key"


class ConfigError(Exception):
    """配置文件缺失或内容不完整。"""


@dataclass(frozen=True)
class LLMConfig:
    """大模型连接配置。"""

    base_url: str
    model_name: str
    api_key: str


@dataclass(frozen=True)
class SearchConfig:
    """联网搜索配置（可选能力，缺少时不阻断程序启动）。"""

    api_key: str = ""


def load_config(config_path: Union[str, Path] = DEFAULT_CONFIG_FILE) -> LLMConfig:
    """读取配置文件并返回 LLMConfig。

    顶层导出：base_url、model_name、api_key（以 LLMConfig 字段形式提供）。
    """
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}")

    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
        section = parser[CONFIG_SECTION]
        base_url = section["base_url"].strip()
        model_name = section["model_name"].strip()
        api_key = section["api_key"].strip()
    except (KeyError, configparser.Error) as exc:
        raise ConfigError(f"配置缺失或格式错误：{exc}") from exc

    missing = [
        name
        for name, value in (
            ("base_url", base_url),
            ("model_name", model_name),
            ("api_key", api_key),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"配置缺失：{', '.join(missing)}")

    return LLMConfig(base_url=base_url, model_name=model_name, api_key=api_key)


def load_search_config(config_path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> SearchConfig:
    """读取可选的 [search] 小节。

    联网搜索属于可选能力：小节缺失、Key 为空或文件不可读时返回空 Key，
    由 searchWeb 工具把「未配置」作为结构化错误反馈给模型，而不是抛异常。
    """
    path = Path(config_path)
    if not path.exists():
        return SearchConfig()

    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
        if not parser.has_section(SEARCH_SECTION):
            return SearchConfig()
        api_key = parser.get(SEARCH_SECTION, SEARCH_API_KEY_OPTION, raw=True, fallback="")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return SearchConfig()

    return SearchConfig(api_key=(api_key or "").strip())
