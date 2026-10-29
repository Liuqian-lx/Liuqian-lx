"""联网搜索工具：searchWeb。

调用百度千帆「百度AI搜索」接口（POST /v2/ai_search/web_search），
把返回的 references 归一化为「标题 / 链接 / 摘要」文本，供大模型二次组织回答。

接口文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
- 鉴权：Authorization: Bearer <API Key>
- 请求体：{"messages": [{"role": "user", "content": query}]}
- 响应：{"references": [{"title", "url", "content", ...}], "request_id": ...}

API Key 读取自项目根目录 config.ini 的 [search] 小节，不在代码中硬编码。
所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import DEFAULT_CONFIG_PATH, load_search_config

SEARCH_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
REQUEST_TIMEOUT = 10
CONFIG_PATH = DEFAULT_CONFIG_PATH

MISSING_KEY_ERROR = (
    "未配置百度千帆搜索 API Key，"
    "请在 config.ini 的 [search] 小节填写 baidu_qianfan_api_key"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "searchWeb",
            "description": (
                "联网搜索互联网上的最新公开信息，返回相关网页的标题、URL链接和内容摘要；"
                "当用户询问时事新闻、最新数据、近期事件、模型训练截止后的新信息时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    }
                },
                "required": ["query"],
            },
        },
    },
]


def searchWeb(query) -> dict:
    """联网搜索给定关键词，返回整理后的参考来源文本。"""
    try:
        text = _normalize_query(query)
        if not text:
            return {"success": False, "error": "搜索关键词不能为空"}

        api_key = load_search_config(CONFIG_PATH).api_key
        if not api_key:
            return {"success": False, "error": MISSING_KEY_ERROR}

        payload = {"messages": [{"role": "user", "content": text}]}
        try:
            status, body = _post_json(SEARCH_ENDPOINT, payload, api_key, REQUEST_TIMEOUT)
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            return {
                "success": False,
                "error": f"搜索接口返回错误：HTTP {exc.code}，{detail}",
            }
        except urllib.error.URLError as exc:
            return {
                "success": False,
                "error": f"网络请求失败：{exc.reason}，请检查网络后重试",
            }
        except (TimeoutError, socket.timeout) as exc:
            return {
                "success": False,
                "error": f"网络请求失败：请求超时（{exc or '10 秒'}），请检查网络后重试",
            }
        except OSError as exc:
            return {
                "success": False,
                "error": f"网络请求失败：{exc}，请检查网络后重试",
            }

        if status != 200:
            return {
                "success": False,
                "error": f"搜索接口返回错误：HTTP {status}，{_body_error_message(body)}",
            }

        try:
            data = json.loads(body)
        except (ValueError, TypeError) as exc:
            return {"success": False, "error": f"搜索接口返回格式异常：{exc}"}
        if not isinstance(data, dict):
            return {"success": False, "error": "搜索接口返回格式异常：响应不是 JSON 对象"}

        # 少数情况下 HTTP 200 但业务码表示失败
        code = data.get("code")
        if code not in (None, "", 0, "0"):
            message = data.get("message") or data.get("msg") or "未知错误"
            return {
                "success": False,
                "error": f"搜索接口返回错误：{code}，{message}",
            }

        references = _extract_references(data)
        if references is None:
            return {
                "success": False,
                "error": "搜索接口返回格式异常：缺少 references 字段",
            }
        if not references:
            return {"success": True, "result": "未检索到相关结果，请更换关键词后重试"}

        return {"success": True, "result": _format_references(text, references)}
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"搜索失败：{exc}"}


def _normalize_query(query: Any) -> str:
    if isinstance(query, str):
        return query.strip()
    if query is None:
        return ""
    return str(query).strip()


def _post_json(
    url: str,
    payload: Dict[str, Any],
    api_key: str,
    timeout: float,
) -> Tuple[int, str]:
    """发送 POST JSON 请求，返回 (HTTP 状态码, 响应文本)。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", None) or response.getcode()
        raw = response.read()
    return int(status), raw.decode("utf-8", errors="replace")


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """从 HTTPError 响应体中尽量提取可读的错误信息。"""
    try:
        raw = exc.read()
    except Exception:
        raw = b""
    text = raw.decode("utf-8", errors="replace").strip() if raw else ""
    if text:
        message = _body_error_message(text)
        return message or text
    return str(getattr(exc, "reason", "") or "未知错误")


def _body_error_message(body: str) -> str:
    """从响应体 JSON 中提取 message/msg，解析失败时返回原文。"""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body.strip() or "未知错误"

    if isinstance(data, dict):
        for key in ("message", "msg", "error_msg", "error"):
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("code")
            if value:
                return str(value)
    return body.strip() or "未知错误"


def _extract_references(data: Dict[str, Any]) -> Optional[List[Any]]:
    """防御性提取 references，兼容常见嵌套位置与 results/items 别名。

    返回 None 表示响应中完全没有来源字段（视为格式异常）；
    返回 [] 表示结构正常但结果为空。
    """
    holders: List[Dict[str, Any]] = [data]
    for key in ("data", "result", "response"):
        nested = data.get(key)
        if isinstance(nested, dict):
            holders.append(nested)

    for holder in holders:
        for key in ("references", "results", "items"):
            value = holder.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for inner_key in ("references", "results", "items", "list"):
                    inner = value.get(inner_key)
                    if isinstance(inner, list):
                        return inner
                return [value]

    # 某些网关直接把结果数组放在 data 下
    nested_data = data.get("data")
    if isinstance(nested_data, list):
        return nested_data
    return None


def _format_references(query: str, references: Sequence[Any]) -> str:
    lines = [f"搜索「{query}」共找到 {len(references)} 条参考结果："]
    for index, item in enumerate(references, 1):
        if isinstance(item, dict):
            title = _first_text(item, ("title", "name"), "（无标题）")
            url = _first_text(item, ("url", "link"), "（无链接）")
            summary = _first_text(item, ("summary", "content", "snippet"), "（无摘要）")
        else:
            title, url, summary = "（无标题）", "（无链接）", _one_line(str(item))

        lines.append(f"{index}. 标题：{title}")
        lines.append(f"   链接：{url}")
        lines.append(f"   摘要：{summary}")
    return "\n".join(lines)


def _first_text(item: Dict[str, Any], keys: Sequence[str], default: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = _one_line(str(value))
        if text:
            return text
    return default


def _one_line(text: str) -> str:
    """压缩换行与连续空白，保证每条结果只占一行，便于模型阅读。"""
    return " ".join(text.split())


TOOL_MAP = {
    "searchWeb": searchWeb,
}
