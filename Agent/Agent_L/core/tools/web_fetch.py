"""网页正文提取工具：fetchWebPage。

通过本地 curl 抓取网页 HTML（参数列表方式，不使用 shell），
再用 trafilatura 提取正文并转换为 Markdown，去除导航、广告、页脚、侧边栏等噪声。

所有异常都转换为 {"success": False, "error": ...} 返回，不向上抛出。
本模块只依赖 core 层能力，不包含任何界面代码。
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:  # 未安装时在调用阶段返回结构化错误，保证 core 仍可导入
    trafilatura = None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
CURL_TIMEOUT = 15
MAX_MARKDOWN_CHARS = 8000
STATUS_MARKER = "__AGENT_L_HTTP_STATUS__"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetchWebPage",
            "description": (
                "抓取指定网页的正文内容并转换为 Markdown，保留标题、段落、列表、表格和超链接，"
                "自动去除导航栏、广告、页脚等无关内容；当用户给出网页链接并希望阅读、总结或"
                "提取该页面正文时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "目标网页地址，必须以 http:// 或 https:// 开头",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


def fetchWebPage(url) -> dict:
    """抓取网页正文并返回 {"url": ..., "markdown": ...}。"""
    try:
        target = _normalize_url(url)
        if not _is_valid_url(target):
            return {"success": False, "error": "URL 不能为空或格式无效"}

        try:
            status, raw_html = _run_curl(target)
        except FileNotFoundError:
            return {"success": False, "error": "本地未检测到 curl 程序，无法执行网页抓取"}
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"网页访问失败：请求超时（超过 {CURL_TIMEOUT} 秒）",
            }
        except OSError as exc:
            return {"success": False, "error": f"网页访问失败：{exc}"}
        except RuntimeError as exc:
            return {"success": False, "error": f"网页访问失败：{exc}"}

        if 400 <= status <= 599:
            return {
                "success": False,
                "error": f"网页请求错误，HTTP 状态码：{status}",
            }
        if not 200 <= status < 300:
            return {
                "success": False,
                "error": f"网页访问失败：HTTP 状态码：{status}",
            }

        try:
            html = _decode_html(raw_html)
            markdown = _extract_markdown(html, target)
        except Exception as exc:
            return {"success": False, "error": f"网页正文提取失败：{exc}"}

        if not markdown:
            return {"success": False, "error": "未能从该网页提取到有效正文内容"}

        return {
            "success": True,
            "result": {"url": target, "markdown": _truncate(markdown)},
        }
    except Exception as exc:
        # 兜底：任何未预期异常都转换为工具结果，保证会话流程不中断
        return {"success": False, "error": f"网页正文提取失败：{exc}"}


def _normalize_url(url: Any) -> str:
    if isinstance(url, str):
        return url.strip()
    if url is None:
        return ""
    return str(url).strip()


def _is_valid_url(url: str) -> bool:
    """只接受 http/https 且带主机名的地址。"""
    if not url or len(url) > 4096 or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _run_curl(url: str) -> Tuple[int, bytes]:
    """用本地 curl 抓取网页，返回 (HTTP 状态码, 响应体字节)。

    使用参数列表执行，绝不经过 shell；curl 自身与 subprocess 均设置 15 秒超时。
    """
    command = [
        "curl",
        "-sS",
        "-L",
        "--compressed",
        "--max-time",
        str(CURL_TIMEOUT),
        "-A",
        USER_AGENT,
        "-w",
        f"\n{STATUS_MARKER}%{{http_code}}",
        url,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        timeout=CURL_TIMEOUT,
        shell=False,
        check=False,
    )

    stdout = completed.stdout or b""
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    marker = STATUS_MARKER.encode("ascii")

    if marker in stdout:
        body, _, status_part = stdout.rpartition(marker)
        try:
            status = int(status_part.decode("ascii", errors="replace").strip())
        except ValueError:
            status = 0
    else:
        body, status = stdout, 0

    if completed.returncode != 0:
        reason = stderr or f"curl 退出码 {completed.returncode}"
        raise RuntimeError(reason)
    if status == 0:
        raise RuntimeError(stderr or "未能获取 HTTP 状态码")
    return status, body


def _decode_html(raw: bytes) -> str:
    """按 <meta charset> 或常见编码解码 HTML，避免中文页面乱码。"""
    if not raw:
        return ""

    encodings = []
    match = re.search(
        rb"charset\s*=\s*[\"']?\s*([\w.-]+)",
        raw[:4096],
        re.IGNORECASE,
    )
    if match:
        encodings.append(match.group(1).decode("ascii", errors="ignore"))
    encodings.extend(("utf-8", "gb18030"))

    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_markdown(html: str, url: str) -> str:
    """用 trafilatura 提取正文并输出 Markdown。"""
    if trafilatura is None:
        raise RuntimeError("未安装 trafilatura，请先执行 pip install trafilatura")
    if not html or not html.strip():
        return ""

    options = {
        "url": url,
        "output_format": "markdown",
        "include_formatting": True,
        "include_links": True,
        "include_tables": True,
        "include_images": False,
    }
    # 优先走精度模式：保留 Markdown 结构，同时去掉导航/广告/页脚等噪声；
    # 若精度模式没有提取到内容，再退回默认模式，避免短页面被误判为空。
    markdown = trafilatura.extract(html, favor_precision=True, **options)
    if not markdown:
        markdown = trafilatura.extract(html, **options)
    markdown = (markdown or "").strip()
    if not markdown:
        return ""

    # 正文中通常已包含标题；仅当标题缺失时用页面元数据补一个一级标题
    try:
        metadata = trafilatura.extract_metadata(html, default_url=url)
        title = (getattr(metadata, "title", "") or "").strip()
    except Exception:
        title = ""
    if title and title not in markdown[:300]:
        markdown = f"# {title}\n\n{markdown}"
    return markdown


def _truncate(markdown: str) -> str:
    if len(markdown) <= MAX_MARKDOWN_CHARS:
        return markdown
    return (
        markdown[:MAX_MARKDOWN_CHARS]
        + f"\n\n...（正文已截断，仅保留前 {MAX_MARKDOWN_CHARS} 个字符）"
    )


TOOL_MAP = {
    "fetchWebPage": fetchWebPage,
}
