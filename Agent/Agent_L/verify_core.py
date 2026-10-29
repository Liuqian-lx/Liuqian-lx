"""core 层独立验证脚本（不导入 tui，不访问网络）。

用法：
    python verify_core.py

它用假的 LLM 客户端驱动完整的工具调用闭环，用来证明：
1. core 层可以在完全没有 tui 的情况下独立运行；
2. 14 个工具、流式回调、工具闭环、历史加载/保存均正常；
3. searchWeb 的配置缺失/空 query/网络与 HTTP 异常/结果归一化均可离线验证；
4. fetchWebPage 的空/非法 URL、curl 缺失/超时、HTTP 错误、解析异常、空正文、
   截断与 trafilatura 正文提取均可离线验证。
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

from core.config import load_config
from core.llm_client import LLMResponse, ToolCall
from core.session import ChatSession
from core.tools import TOOL_MAP, TOOLS, execute_tool, web_fetch, web_search

BASE_DIR = Path(__file__).resolve().parent


class StubLLM:
    """两轮对话的假模型：第一轮调用 list_directory，第二轮输出文本。"""

    def __init__(self, target_dir: Path):
        self._target_dir = target_dir
        self.round = 0
        self.received_tools = None

    def stream_chat(self, messages, tools=None, on_text=None, on_tool_call=None):
        self.round += 1
        self.received_tools = tools
        if self.round == 1:
            call = ToolCall(
                id="call_1",
                name="list_directory",
                arguments=json.dumps({"dir_path": str(self._target_dir)}),
            )
            if on_tool_call is not None:
                on_tool_call(call)
            return LLMResponse(content="", tool_calls=[call])

        text = "已为你列出目录内容。"
        if on_text is not None:
            for char in text:
                on_text(char)
        return LLMResponse(content=text)


class SearchStubLLM:
    """两轮对话的假模型：第一轮调用 searchWeb，第二轮输出文本。"""

    def __init__(self, query: str):
        self._query = query
        self.round = 0

    def stream_chat(self, messages, tools=None, on_text=None, on_tool_call=None):
        self.round += 1
        if self.round == 1:
            call = ToolCall(
                id="call_search",
                name="searchWeb",
                arguments=json.dumps({"query": self._query}),
            )
            if on_tool_call is not None:
                on_tool_call(call)
            return LLMResponse(content="", tool_calls=[call])

        text = "已根据搜索结果整理回答。"
        if on_text is not None:
            on_text(text)
        return LLMResponse(content=text)


def main() -> int:
    passed = 0

    def ok(label: str, condition: bool) -> None:
        nonlocal passed
        if not condition:
            print(f"[失败] {label}")
            raise SystemExit(1)
        passed += 1
        print(f"[通过] {label}")

    config = load_config(BASE_DIR / "config.ini")
    ok("配置读取（base_url/model_name/api_key）", all((config.base_url, config.model_name, config.api_key)))
    print(f"       base_url = {config.base_url}")
    print(f"       model    = {config.model_name}")

    names = [tool["function"]["name"] for tool in TOOLS]
    ok("工具总数为 14 且无重名", len(names) == 14 and len(set(names)) == 14)
    ok("searchWeb 已注册到 schema 与 TOOL_MAP", "searchWeb" in names and "searchWeb" in TOOL_MAP)

    date_result = execute_tool("getDate", "")
    ok("内置工具 getDate", bool(date_result.get("success") and date_result.get("result")))
    leap_result = execute_tool("isLeapYear", '{"year": 2024}')
    ok("内置工具 isLeapYear", bool(leap_result.get("success")) and "是闰年" in leap_result.get("result", ""))

    workdir = Path(tempfile.mkdtemp(prefix="agent_l_core_"))
    try:
        demo_dir = workdir / "demo"
        ok(
            "文件工具 create_directory",
            execute_tool("create_directory", json.dumps({"dir_path": str(demo_dir)})).get("success") is True,
        )
        ok(
            "文件工具 create_file",
            execute_tool(
                "create_file",
                json.dumps(
                    {"dir_path": str(demo_dir), "file_name": "hello.txt", "content": "hello"},
                ),
            ).get("success")
            is True,
        )
        ok(
            "文件工具 read_file_content",
            execute_tool(
                "read_file_content",
                json.dumps({"file_path": str(demo_dir / "hello.txt")}),
            ).get("result")
            == "hello",
        )
        ok(
            "文件工具 edit_file(append)",
            execute_tool(
                "edit_file",
                json.dumps(
                    {"file_path": str(demo_dir / "hello.txt"), "content": " world", "mode": "append"},
                ),
            ).get("success")
            is True,
        )
        listing = execute_tool("list_directory", json.dumps({"dir_path": str(demo_dir)}))
        ok("文件工具 list_directory", listing.get("success") is True and listing.get("result")[0]["name"] == "hello.txt")

        stub = StubLLM(demo_dir)
        history_file = workdir / "chat_history.json"
        session = ChatSession(stub, history_file=history_file)
        chunks: list[str] = []
        events = []
        result = session.send_message(
            "看看目录里有什么",
            on_text=chunks.append,
            on_tool_result=events.append,
        )

        ok("会话返回最终文本", result.content == "已为你列出目录内容。")
        ok("流式文本回调逐字触发", "".join(chunks) == result.content and len(chunks) > 1)
        ok("工具调用闭环执行成功", len(result.tool_events) == 1 and result.tool_events[0].success)
        ok("工具结果已回填到上下文", any(m.get("role") == "tool" for m in session.get_history()))
        ok("对话历史自动保存", history_file.exists())

        restored = ChatSession(stub, history_file=history_file)
        ok("对话历史可重新加载", len(restored.get_history()) == 4)

        # ---------------------------------------------------------- searchWeb 离线自测
        search_schema = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "searchWeb"
        )
        ok(
            "searchWeb schema：query 为唯一必填参数",
            search_schema["parameters"]["required"] == ["query"]
            and search_schema["parameters"]["properties"]["query"]["type"] == "string",
        )

        missing_cfg = workdir / "config_missing_search.ini"
        missing_cfg.write_text("[llm]\nbase_url = http://example.com\n", encoding="utf-8")
        empty_cfg = workdir / "config_empty_key.ini"
        empty_cfg.write_text("[search]\nbaidu_qianfan_api_key =   \n", encoding="utf-8")
        key_cfg = workdir / "config_test_key.ini"
        key_cfg.write_text("[search]\nbaidu_qianfan_api_key = test-key\n", encoding="utf-8")

        original_config_path = web_search.CONFIG_PATH
        original_post = web_search._post_json
        try:
            web_search.CONFIG_PATH = key_cfg
            empty_query = execute_tool("searchWeb", json.dumps({"query": "   "}))
            ok(
                "searchWeb 空 query 返回结构化错误",
                empty_query.get("success") is False
                and empty_query.get("error") == "搜索关键词不能为空",
            )

            web_search.CONFIG_PATH = missing_cfg
            missing_key = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb 缺少 [search] 小节返回未配置错误",
                missing_key.get("success") is False
                and "未配置百度千帆搜索 API Key" in missing_key.get("error", ""),
            )

            web_search.CONFIG_PATH = empty_cfg
            empty_key = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb Key 为空返回未配置错误",
                empty_key.get("success") is False
                and "baidu_qianfan_api_key" in empty_key.get("error", ""),
            )

            web_search.CONFIG_PATH = key_cfg

            def network_error(*args, **kwargs):
                raise urllib.error.URLError("getaddrinfo failed")

            web_search._post_json = network_error
            network_result = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb 网络异常返回结构化错误",
                network_result.get("success") is False
                and "网络请求失败" in network_result.get("error", "")
                and "请检查网络后重试" in network_result.get("error", ""),
            )

            def http_error(url, payload, api_key, timeout):
                raise urllib.error.HTTPError(
                    url,
                    403,
                    "Forbidden",
                    {},
                    io.BytesIO('{"message": "invalid api key"}'.encode("utf-8")),
                )

            web_search._post_json = http_error
            http_result = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb HTTP 非 200 返回结构化错误",
                http_result.get("success") is False
                and "HTTP 403" in http_result.get("error", "")
                and "invalid api key" in http_result.get("error", ""),
            )

            web_search._post_json = lambda *args, **kwargs: (200, "not-json")
            bad_json = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb 非法 JSON 返回格式异常",
                bad_json.get("success") is False
                and "搜索接口返回格式异常" in bad_json.get("error", ""),
            )

            web_search._post_json = lambda *args, **kwargs: (500, '{"message": "server error"}')
            status_result = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb 直接返回非 200 状态码也能识别",
                status_result.get("success") is False
                and "HTTP 500" in status_result.get("error", "")
                and "server error" in status_result.get("error", ""),
            )

            def success_response(*args, **kwargs):
                return 200, json.dumps(
                    {
                        "request_id": "req-test",
                        "data": {
                            "references": [
                                {
                                    "name": "示例标题",
                                    "link": "https://example.com/a",
                                    "snippet": "示例摘要",
                                },
                                {
                                    "title": "第二条",
                                    "url": "https://example.com/b",
                                    "content": "第二条摘要",
                                },
                            ]
                        },
                    },
                    ensure_ascii=False,
                )

            web_search._post_json = success_response
            normalized = execute_tool("searchWeb", json.dumps({"query": "测试关键词"}))
            text = normalized.get("result", "")
            ok(
                "searchWeb 结果归一化为标题/链接/摘要",
                normalized.get("success") is True
                and "搜索「测试关键词」共找到 2 条参考结果：" in text
                and "1. 标题：示例标题" in text
                and "链接：https://example.com/a" in text
                and "摘要：示例摘要" in text
                and "2. 标题：第二条" in text
                and "摘要：第二条摘要" in text,
            )

            search_session = ChatSession(
                SearchStubLLM("测试关键词"),
                history_file=workdir / "search_history.json",
            )
            search_result = search_session.send_message("帮我搜一下")
            ok(
                "searchWeb 通过现有工具闭环执行并回填结果",
                search_result.content == "已根据搜索结果整理回答。"
                and len(search_result.tool_events) == 1
                and search_result.tool_events[0].success
                and any(
                    message.get("role") == "tool"
                    and "示例标题" in (message.get("content") or "")
                    for message in search_session.get_history()
                ),
            )

            web_search._post_json = lambda *args, **kwargs: (200, '{"references": []}')
            empty_result = execute_tool("searchWeb", json.dumps({"query": "测试"}))
            ok(
                "searchWeb 空结果返回友好提示",
                empty_result.get("success") is True
                and empty_result.get("result") == "未检索到相关结果，请更换关键词后重试",
            )
        finally:
            web_search.CONFIG_PATH = original_config_path
            web_search._post_json = original_post

        # ---------------------------------------------------------- fetchWebPage 离线自测
        fetch_schema = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "fetchWebPage"
        )
        ok(
            "fetchWebPage 已注册，schema 以 url 为唯一必填参数",
            "fetchWebPage" in TOOL_MAP
            and fetch_schema["parameters"]["required"] == ["url"]
            and fetch_schema["parameters"]["properties"]["url"]["type"] == "string",
        )

        invalid_urls = ["", "   ", "not-a-url", "ftp://example.com/a", "https://"]
        invalid_results = [
            execute_tool("fetchWebPage", json.dumps({"url": value}))
            for value in invalid_urls
        ]
        ok(
            "fetchWebPage 空/非法 URL 返回统一错误",
            all(
                result.get("success") is False
                and result.get("error") == "URL 不能为空或格式无效"
                for result in invalid_results
            ),
        )

        original_run_curl = web_fetch._run_curl
        original_extract = web_fetch._extract_markdown
        try:
            def curl_missing(url):
                raise FileNotFoundError("curl")

            web_fetch._run_curl = curl_missing
            missing_curl = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.com"})
            )
            ok(
                "fetchWebPage 本地缺少 curl 返回结构化错误",
                missing_curl.get("success") is False
                and missing_curl.get("error") == "本地未检测到 curl 程序，无法执行网页抓取",
            )

            def curl_timeout(url):
                raise subprocess.TimeoutExpired(["curl"], 15)

            web_fetch._run_curl = curl_timeout
            timeout_result = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.com"})
            )
            ok(
                "fetchWebPage curl 超时返回结构化错误",
                timeout_result.get("success") is False
                and "网页访问失败" in timeout_result.get("error", "")
                and "超时" in timeout_result.get("error", ""),
            )

            def curl_network_error(url):
                raise RuntimeError("Could not resolve host: example.invalid")

            web_fetch._run_curl = curl_network_error
            network_result = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.invalid"})
            )
            ok(
                "fetchWebPage 网络/DNS 失败返回结构化错误",
                network_result.get("success") is False
                and network_result.get("error")
                == "网页访问失败：Could not resolve host: example.invalid",
            )

            web_fetch._run_curl = lambda url: (404, b"not found")
            http_result = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.com/missing"})
            )
            ok(
                "fetchWebPage HTTP 4xx 返回状态码错误",
                http_result.get("success") is False
                and http_result.get("error") == "网页请求错误，HTTP 状态码：404",
            )

            web_fetch._run_curl = lambda url: (200, b"<html></html>")

            def extract_failure(html, url):
                raise ValueError("bad html")

            web_fetch._extract_markdown = extract_failure
            extract_error = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.com"})
            )
            ok(
                "fetchWebPage 解析异常返回结构化错误",
                extract_error.get("success") is False
                and extract_error.get("error") == "网页正文提取失败：bad html",
            )

            web_fetch._extract_markdown = lambda html, url: ""
            empty_body = execute_tool(
                "fetchWebPage", json.dumps({"url": "https://example.com"})
            )
            ok(
                "fetchWebPage 空正文返回结构化错误",
                empty_body.get("success") is False
                and empty_body.get("error") == "未能从该网页提取到有效正文内容",
            )

            long_markdown = "正文内容" * 3000
            web_fetch._extract_markdown = lambda html, url: long_markdown
            success = execute_tool(
                "fetchWebPage",
                json.dumps({"url": "https://example.com/article"}),
            )
            payload = success.get("result") or {}
            ok(
                "fetchWebPage 成功返回 url/markdown 并按 8000 字符截断",
                success.get("success") is True
                and payload.get("url") == "https://example.com/article"
                and payload.get("markdown", "").startswith(long_markdown[:100])
                and len(payload.get("markdown", "")) < len(long_markdown)
                and "已截断" in payload.get("markdown", ""),
            )

            sample_html = """<!doctype html><html><head><meta charset="utf-8">
<title>测试文章标题</title></head><body>
<nav>首页 产品 关于我们</nav><header>广告位</header>
<article><h1>测试文章标题</h1>
<p>这是第一段正文，介绍文章的主要内容。</p>
<ul><li>列表项一</li><li>列表项二</li></ul>
<table><tr><th>名称</th><th>数量</th></tr><tr><td>苹果</td><td>3</td></tr></table>
<p>了解更多请访问 <a href="https://example.com/more">示例链接</a>。</p>
</article><aside>侧边栏推荐</aside><footer>版权所有</footer>
</body></html>"""
            web_fetch._run_curl = lambda url: (200, sample_html.encode("utf-8"))
            web_fetch._extract_markdown = original_extract
            native = execute_tool(
                "fetchWebPage",
                json.dumps({"url": "https://example.com/article"}),
            )
            native_markdown = (native.get("result") or {}).get("markdown", "")
            ok(
                "fetchWebPage trafilatura 保留 Markdown 结构并去除噪声",
                native.get("success") is True
                and "# " in native_markdown
                and "- 列表项一" in native_markdown
                and "| 名称 | 数量 |" in native_markdown
                and "](https://example.com/more)" in native_markdown
                and "首页 产品" not in native_markdown
                and "版权所有" not in native_markdown,
            )
        finally:
            web_fetch._run_curl = original_run_curl
            web_fetch._extract_markdown = original_extract

        fetch_source = (BASE_DIR / "core" / "tools" / "web_fetch.py").read_text(
            encoding="utf-8"
        )
        ok(
            "fetchWebPage 使用 curl 参数列表且不存在 shell=True",
            '"curl"' in fetch_source
            and "subprocess.run(" in fetch_source
            and "shell=True" not in fetch_source,
        )

        ok("全程未导入 tui 层", "tui" not in sys.modules)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\ncore 层验证全部通过，共 {passed} 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
