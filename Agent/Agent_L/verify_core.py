"""core 层独立验证脚本（不导入 tui，不访问网络）。

用法：
    python verify_core.py

它用假的 LLM 客户端驱动完整的工具调用闭环，用来证明：
1. core 层可以在完全没有 tui 的情况下独立运行；
2. 17 个工具、流式回调、工具闭环、历史加载/保存均正常；
3. searchWeb 的配置缺失/空 query/网络与 HTTP 异常/结果归一化均可离线验证；
4. fetchWebPage 的空/非法 URL、curl 缺失/超时、HTTP 错误、解析异常、空正文、
   截断与 trafilatura 正文提取均可离线验证；
5. RunCli 的空命令、参数列表拼装、命令不存在、超时、系统错误、输出截断、
   非 0 退出码、无 shell=True 均可离线验证（只执行安全的内置命令）；
6. Skill 扫描/元数据提取/惰性加载、system prompt 注入、loadSkill 的
   SKILL.md 与附件读取、路径穿越拦截、多匹配候选与各类错误均可离线验证；
7. createSkill 的名称校验、防覆盖、路径沙箱、Frontmatter 规范化与
   SkillManager 即时刷新均可离线验证。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

from core.config import load_config
from core.llm_client import LLMResponse, ToolCall
from core.session import ChatSession
from core.skills import (
    SkillManager,
    get_active_manager,
    parse_frontmatter,
    set_active_manager,
)
from core.tools import TOOL_MAP, TOOLS, execute_tool, run_cli, web_fetch, web_search

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


class CaptureStubLLM:
    """单轮假模型：记录实际收到的 messages，用于检查 system prompt 注入位置。"""

    def __init__(self):
        self.messages = None

    def stream_chat(self, messages, tools=None, on_text=None, on_tool_call=None):
        self.messages = list(messages)
        return LLMResponse(content="收到。")


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
    ok("工具总数为 17 且无重名", len(names) == 17 and len(set(names)) == 17)
    ok("searchWeb 已注册到 schema 与 TOOL_MAP", "searchWeb" in names and "searchWeb" in TOOL_MAP)
    ok("loadSkill 已注册到 schema 与 TOOL_MAP", "loadSkill" in names and "loadSkill" in TOOL_MAP)
    ok(
        "createSkill 已注册到 schema 与 TOOL_MAP",
        "createSkill" in names and "createSkill" in TOOL_MAP,
    )

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

        # ---------------------------------------------------------- RunCli 离线自测
        run_schema = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "RunCli"
        )
        run_params = run_schema["parameters"]["properties"]
        ok(
            "RunCli 已注册，schema 以 command 为必填、args 为字符串数组",
            "RunCli" in TOOL_MAP
            and run_schema["parameters"]["required"] == ["command"]
            and run_params["command"]["type"] == "string"
            and run_params["args"]["type"] == "array"
            and run_params["args"]["items"]["type"] == "string",
        )

        empty_command = execute_tool("RunCli", json.dumps({"command": "   "}))
        missing_command = execute_tool("RunCli", "{}")
        ok(
            "RunCli 空命令/缺少 command 返回结构化错误",
            empty_command.get("success") is False
            and empty_command.get("error") == "命令名称不能为空"
            and missing_command.get("success") is False
            and missing_command.get("error") == "命令名称不能为空",
        )

        bad_args = execute_tool("RunCli", json.dumps({"command": "python", "args": "-V"}))
        ok(
            "RunCli args 非数组返回结构化错误",
            bad_args.get("success") is False
            and bad_args.get("error") == "参数 args 必须是字符串数组",
        )

        not_found = execute_tool(
            "RunCli", json.dumps({"command": "agent_l_missing_command_for_verify"})
        )
        ok(
            "RunCli 不存在的命令返回未找到",
            not_found.get("success") is False
            and not_found.get("error") == "未找到命令：agent_l_missing_command_for_verify",
        )

        original_run_process = run_cli._run_process
        captured = {}
        try:
            def fake_run(argv):
                captured["argv"] = list(argv)
                return subprocess.CompletedProcess(argv, 0, b"ok", b"")

            run_cli._run_process = fake_run
            with_args = execute_tool(
                "RunCli",
                json.dumps({"command": "python", "args": ["-c", "print('hi')"]}),
            )
            ok(
                "RunCli 程序名与参数按列表拼装",
                with_args.get("success") is True
                and captured["argv"] == ["python", "-c", "print('hi')"]
                and with_args["result"]["command"] == "python"
                and with_args["result"]["args"] == ["-c", "print('hi')"]
                and with_args["result"]["exit_code"] == 0,
            )

            no_args = execute_tool("RunCli", json.dumps({"command": "python"}))
            ok(
                "RunCli 省略 args 时默认为空列表",
                no_args.get("success") is True
                and captured["argv"] == ["python"]
                and no_args["result"]["args"] == [],
            )

            def long_output_run(argv):
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    b"a" * 5000,
                    b"b" * 4500,
                )

            run_cli._run_process = long_output_run
            truncated = execute_tool("RunCli", json.dumps({"command": "python"}))
            stdout = truncated["result"]["stdout"]
            stderr = truncated["result"]["stderr"]
            ok(
                "RunCli stdout/stderr 各截断到前 4000 字符并标注",
                truncated.get("success") is True
                and stdout == "a" * run_cli.MAX_OUTPUT_CHARS + run_cli.TRUNCATE_MARKER
                and stderr == "b" * run_cli.MAX_OUTPUT_CHARS + run_cli.TRUNCATE_MARKER
                and "输出已截断" in stdout
                and "输出已截断" in stderr,
            )

            def timeout_run(argv):
                raise subprocess.TimeoutExpired(argv, run_cli.TIMEOUT_SECONDS)

            run_cli._run_process = timeout_run
            timeout_result = execute_tool("RunCli", json.dumps({"command": "python"}))
            ok(
                "RunCli 执行超时返回结构化错误",
                timeout_result.get("success") is False
                and timeout_result.get("error") == "命令执行超时（30秒）",
            )

            def permission_run(argv):
                raise PermissionError("拒绝访问")

            run_cli._run_process = permission_run
            permission_result = execute_tool("RunCli", json.dumps({"command": "python"}))
            ok(
                "RunCli 权限不足等系统错误返回结构化错误",
                permission_result.get("success") is False
                and permission_result.get("error") == "命令执行失败：拒绝访问",
            )
        finally:
            run_cli._run_process = original_run_process

        real_ok = execute_tool(
            "RunCli",
            json.dumps({"command": sys.executable, "args": ["-c", "print('agent-l-ok')"]}),
        )
        ok(
            "RunCli 实际执行安全命令返回 stdout 与退出码 0",
            real_ok.get("success") is True
            and real_ok["result"]["exit_code"] == 0
            and "agent-l-ok" in real_ok["result"]["stdout"],
        )

        real_fail = execute_tool(
            "RunCli",
            json.dumps(
                {
                    "command": sys.executable,
                    "args": [
                        "-c",
                        "import sys; sys.stderr.write('boom'); sys.exit(3)",
                    ],
                }
            ),
        )
        ok(
            "RunCli 非 0 退出码仍返回 success=true 并携带 exit_code",
            real_fail.get("success") is True
            and real_fail["result"]["exit_code"] == 3
            and "boom" in real_fail["result"]["stderr"],
        )

        run_cli_source = (BASE_DIR / "core" / "tools" / "run_cli.py").read_text(
            encoding="utf-8"
        )
        ok(
            "RunCli 使用参数列表执行且不存在 shell=True",
            "subprocess.run(" in run_cli_source
            and "shell=False" in run_cli_source
            and "[name, *arg_list]" in run_cli_source
            and "shell=True" not in run_cli_source,
        )

        # ---------------------------------------------------------- Skill 离线自测
        skills_base = workdir / ".agents" / "skills"

        def write_skill(dirname, content=None, files=None, raw=None):
            directory = skills_base / dirname
            directory.mkdir(parents=True, exist_ok=True)
            if raw is not None:
                (directory / "SKILL.md").write_bytes(raw)
            else:
                (directory / "SKILL.md").write_text(content or "", encoding="utf-8")
            for relative, text in (files or {}).items():
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            return directory

        pdf_dir = write_skill(
            "pdf",
            "---\nname: pdf\ndescription: 处理 PDF 文档的读取与摘要\n---\n\n"
            "# PDF Skill\n\n完整用法正文。\n",
            {
                "notes/tips.md": "TIPS-内容",
                "notes/intro.md": "INTRO-A",
                "extra/intro.md": "INTRO-B",
            },
        )
        (pdf_dir / "binary.bin").write_bytes(b"\xff\xfe\x00bad")

        write_skill(
            "writer",
            "---\nname: writer\ndescription: >-\n  写作与润色\n  助手\n---\n\n写作正文。\n",
        )
        # 正文含非法 UTF-8 字节：若初始化读取全文就会解析失败
        write_skill(
            "lazy",
            raw=(
                "---\nname: lazy\ndescription: 懒加载元数据测试\n---\n".encode("utf-8")
                + b"\xff\xfe\x00BODY"
            ),
        )
        write_skill("broken", "# 没有 Frontmatter 的正文\n")
        write_skill("partial", "---\nname: partial-skill\n---\n正文\n")
        write_skill("pdf-copy", "---\nname: pdf\ndescription: 重复名称\n---\n")
        (skills_base / "empty-dir").mkdir(parents=True, exist_ok=True)
        (skills_base / "README.md").write_text("not a skill", encoding="utf-8")

        secret_file = workdir / ".agents" / "secret.txt"
        secret_file.write_text("TOP-SECRET", encoding="utf-8")

        manager = SkillManager(workdir)
        ok(
            "Skill 扫描：仅一级子目录、按目录名排序、重名保留第一个",
            manager.names == ["lazy", "pdf", "writer"],
        )
        pdf_meta = manager.get("pdf")
        ok(
            "Skill 元数据提取 name/description 与目录",
            pdf_meta is not None
            and pdf_meta.description == "处理 PDF 文档的读取与摘要"
            and pdf_meta.directory == pdf_dir,
        )
        writer_meta = manager.get("writer")
        ok(
            "Skill Frontmatter 支持折叠块标量",
            writer_meta is not None and writer_meta.description == "写作与润色 助手",
        )
        ok(
            "缺少 SKILL.md/Frontmatter/必填字段/重名的 Skill 被静默跳过",
            any("empty-dir" in item and "SKILL.md" in item for item in manager.errors)
            and any("broken" in item and "Frontmatter" in item for item in manager.errors)
            and any(
                "partial" in item and "name 或 description" in item
                for item in manager.errors
            )
            and any("pdf-copy" in item and "名称重复" in item for item in manager.errors)
            and len(manager.errors) == 4,
        )
        ok(
            "Skill 根目录不存在时静默跳过",
            SkillManager(workdir / "no-such-project").names == []
            and SkillManager(workdir / "no-such-project").errors == [],
        )

        skill_session = ChatSession(
            StubLLM(pdf_dir),
            history_file=workdir / "skill_history.json",
            project_root=workdir,
        )
        prompt = skill_session.system_prompt
        ok(
            "Skill 列表按格式追加到 system prompt 且不预载全文",
            "## 可用 Skills" in prompt
            and "- pdf: 处理 PDF 文档的读取与摘要" in prompt
            and "- writer: 写作与润色 助手" in prompt
            and "loadSkill" in prompt
            and "完整用法正文" not in prompt,
        )
        no_skill_session = ChatSession(
            StubLLM(workdir),
            history_file=workdir / "no_skill_history.json",
            project_root=workdir / "no-such-project",
        )
        ok("无可用 Skill 时 system prompt 保持为空", no_skill_session.system_prompt == "")

        capture = CaptureStubLLM()
        capture_session = ChatSession(
            capture,
            history_file=workdir / "capture_history.json",
            project_root=workdir,
        )
        capture_result = capture_session.send_message("你好")
        saved_messages = json.loads(
            (workdir / "capture_history.json").read_text(encoding="utf-8")
        )
        ok(
            "system prompt 仅用于请求，不写入历史文件",
            capture_result.content == "收到。"
            and capture.messages is not None
            and capture.messages[0]["role"] == "system"
            and "## 可用 Skills" in capture.messages[0]["content"]
            and all(item.get("role") != "system" for item in capture_session.get_history())
            and all(item.get("role") != "system" for item in saved_messages),
        )

        skill_schema = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "loadSkill"
        )
        skill_params = skill_schema["parameters"]
        ok(
            "loadSkill schema：name 必填，filename 可选",
            skill_params["required"] == ["name"]
            and skill_params["properties"]["name"]["type"] == "string"
            and skill_params["properties"]["filename"]["type"] == "string",
        )

        previous_manager = get_active_manager()
        set_active_manager(manager)
        try:
            default_read = execute_tool("loadSkill", json.dumps({"name": "pdf"}))
            ok(
                "loadSkill 默认读取 SKILL.md 全文",
                default_read.get("success") is True
                and default_read["result"]["skill_name"] == "pdf"
                and default_read["result"]["file"] == "SKILL.md"
                and "完整用法正文" in default_read["result"]["content"],
            )

            relative_read = execute_tool(
                "loadSkill", json.dumps({"name": "pdf", "filename": "notes/tips.md"})
            )
            ok(
                "loadSkill 读取 Skill 目录内相对路径附件",
                relative_read.get("success") is True
                and relative_read["result"]["file"] == "notes/tips.md"
                and relative_read["result"]["content"] == "TIPS-内容",
            )

            name_read = execute_tool(
                "loadSkill", json.dumps({"name": "pdf", "filename": "tips.md"})
            )
            ok(
                "loadSkill 按文件名递归搜索唯一匹配",
                name_read.get("success") is True
                and name_read["result"]["file"] == "notes/tips.md"
                and name_read["result"]["content"] == "TIPS-内容",
            )

            absolute_read = execute_tool(
                "loadSkill",
                json.dumps(
                    {"name": "pdf", "filename": str(pdf_dir / "notes" / "tips.md")}
                ),
            )
            ok(
                "loadSkill 允许读取 Skill 目录内的绝对路径",
                absolute_read.get("success") is True
                and absolute_read["result"]["content"] == "TIPS-内容",
            )

            traversals = [
                "../secret.txt",
                "notes/../../secret.txt",
                str(secret_file),
            ]
            traversal_results = [
                execute_tool("loadSkill", json.dumps({"name": "pdf", "filename": value}))
                for value in traversals
            ]
            ok(
                "loadSkill 拦截 ../ 与目录外绝对路径穿越",
                all(
                    item.get("success") is False
                    and item.get("error") == "路径超出 Skill 目录范围，禁止访问"
                    for item in traversal_results
                ),
            )

            multi = execute_tool(
                "loadSkill", json.dumps({"name": "pdf", "filename": "intro.md"})
            )
            multi_payload = multi.get("result") or {}
            ok(
                "loadSkill 同名文件多匹配时返回候选路径列表",
                multi.get("success") is True
                and len(multi_payload.get("matches", [])) == 2
                and multi_payload.get("hint") == "存在多个匹配文件，请指定完整路径"
                and all(os.path.isabs(item) for item in multi_payload["matches"]),
            )

            chosen_read = execute_tool(
                "loadSkill",
                json.dumps({"name": "pdf", "filename": multi_payload["matches"][0]}),
            )
            ok(
                "loadSkill 可用候选完整路径再次读取",
                chosen_read.get("success") is True
                and chosen_read["result"]["content"] in ("INTRO-A", "INTRO-B"),
            )

            missing_skill = execute_tool("loadSkill", json.dumps({"name": "missing"}))
            ok(
                "loadSkill 未找到 Skill 返回中文错误",
                missing_skill.get("success") is False
                and missing_skill.get("error") == "未找到指定的 Skill：missing",
            )

            missing_file = execute_tool(
                "loadSkill", json.dumps({"name": "pdf", "filename": "nope.md"})
            )
            ok(
                "loadSkill 未找到附件返回中文错误",
                missing_file.get("success") is False
                and missing_file.get("error") == "Skill 中未找到指定文件：nope.md",
            )

            encoding_error = execute_tool(
                "loadSkill", json.dumps({"name": "pdf", "filename": "binary.bin"})
            )
            ok(
                "loadSkill 非 UTF-8 文件返回编码错误",
                encoding_error.get("success") is False
                and "编码错误" in encoding_error.get("error", ""),
            )

            lazy_read = execute_tool("loadSkill", json.dumps({"name": "lazy"}))
            ok(
                "初始化不读取正文：非法正文字节不影响元数据",
                "lazy" in manager.names
                and lazy_read.get("success") is False
                and "编码错误" in lazy_read.get("error", ""),
            )

            skill_source = (
                BASE_DIR / "core" / "tools" / "skill_loader.py"
            ).read_text(encoding="utf-8")
            ok(
                "loadSkill 使用 realpath + commonpath 实现沙箱",
                "os.path.realpath(" in skill_source
                and "os.path.commonpath(" in skill_source,
            )
        finally:
            set_active_manager(previous_manager)

        # ------------------------------------------------------ createSkill 离线自测
        create_schema = next(
            tool["function"] for tool in TOOLS if tool["function"]["name"] == "createSkill"
        )
        create_params = create_schema["parameters"]
        ok(
            "createSkill schema：name 与 skillContext 必填",
            create_params["required"] == ["name", "skillContext"]
            and create_params["properties"]["name"]["type"] == "string"
            and create_params["properties"]["skillContext"]["type"] == "string",
        )

        previous_cwd = os.getcwd()
        previous_active = get_active_manager()
        os.chdir(workdir)
        try:
            invalid_names = ["", "Bad-Name", "-start", "end-", "../escape", "a/b", "中文"]
            invalid_results = [
                execute_tool(
                    "createSkill",
                    json.dumps({"name": value, "skillContext": "# x"}, ensure_ascii=False),
                )
                for value in invalid_names
            ]
            ok(
                "createSkill 名称仅允许 kebab-case",
                all(
                    item.get("success") is False
                    and item.get("error")
                    == "Skill 名称不合法，仅允许小写字母、数字和连字符（kebab-case 格式）"
                    for item in invalid_results
                )
                and not (workdir / "escape").exists(),
            )

            new_skill_dir = workdir / ".agents" / "skills" / "demo-skill"
            created = execute_tool(
                "createSkill",
                json.dumps(
                    {"name": "demo-skill", "skillContext": "# Demo\n\n这是演示正文。"},
                    ensure_ascii=False,
                ),
            )
            skill_file = new_skill_dir / "SKILL.md"
            created_text = (
                skill_file.read_text(encoding="utf-8") if skill_file.is_file() else ""
            )
            ok(
                "createSkill 创建目录并自动生成 Frontmatter",
                created.get("success") is True
                and created["result"]
                == {
                    "skill_name": "demo-skill",
                    "skill_path": ".agents/skills/demo-skill",
                    "file": "SKILL.md",
                    "message": "Skill 创建成功，已可被加载使用",
                }
                and new_skill_dir.is_dir()
                and created_text.startswith("---\nname: demo-skill\ndescription: ")
                and "这是演示正文" in created_text,
            )

            duplicate = execute_tool(
                "createSkill",
                json.dumps(
                    {"name": "demo-skill", "skillContext": "覆盖尝试"},
                    ensure_ascii=False,
                ),
            )
            ok(
                "createSkill 已存在时拒绝覆盖",
                duplicate.get("success") is False
                and duplicate.get("error") == "Skill demo-skill 已存在，禁止覆盖原有内容"
                and skill_file.read_text(encoding="utf-8") == created_text,
            )

            fixed = execute_tool(
                "createSkill",
                json.dumps(
                    {
                        "name": "fixed-skill",
                        "skillContext": "---\nname: wrong-name\nauthor: me\n---\n"
                        "# 标题\n正文内容。\n",
                    },
                    ensure_ascii=False,
                ),
            )
            fixed_text = (
                workdir / ".agents" / "skills" / "fixed-skill" / "SKILL.md"
            ).read_text(encoding="utf-8")
            fixed_meta = parse_frontmatter(fixed_text) or {}
            ok(
                "createSkill 补全 name/description 并保留其他字段",
                fixed.get("success") is True
                and fixed_meta.get("name") == "fixed-skill"
                and fixed_meta.get("description") == "# 标题 正文内容。"
                and fixed_meta.get("author") == "me",
            )

            kept = execute_tool(
                "createSkill",
                json.dumps(
                    {
                        "name": "kept-skill",
                        "skillContext": "---\nname: kept-skill\n"
                        "description: 已有描述\n---\n正文\n",
                    },
                    ensure_ascii=False,
                ),
            )
            kept_meta = parse_frontmatter(
                (
                    workdir / ".agents" / "skills" / "kept-skill" / "SKILL.md"
                ).read_text(encoding="utf-8")
            ) or {}
            ok(
                "createSkill 保留已有 description",
                kept.get("success") is True
                and kept_meta.get("description") == "已有描述",
            )

            create_manager = SkillManager(workdir)
            set_active_manager(create_manager)
            reloaded = execute_tool(
                "createSkill",
                json.dumps(
                    {"name": "reload-skill", "skillContext": "# 新技能\n正文"},
                    ensure_ascii=False,
                ),
            )
            loaded = execute_tool("loadSkill", json.dumps({"name": "reload-skill"}))
            ok(
                "createSkill 创建后刷新 SkillManager 并可被 loadSkill 读取",
                reloaded.get("success") is True
                and "reload-skill" in create_manager.names
                and loaded.get("success") is True
                and "新技能" in loaded["result"]["content"],
            )

            create_source = (BASE_DIR / "core" / "tools" / "create_skill.py").read_text(
                encoding="utf-8"
            )
            ok(
                "createSkill 使用 realpath + commonpath 实现沙箱",
                "os.path.realpath(" in create_source
                and "os.path.commonpath(" in create_source,
            )
        finally:
            os.chdir(previous_cwd)
            set_active_manager(previous_active)

        core_sources = list((BASE_DIR / "core").rglob("*.py"))
        leaks = [
            path.name
            for path in core_sources
            if re.search(
                r"(?m)^\s*(print|input)\s*\(",
                path.read_text(encoding="utf-8"),
            )
        ]
        ok("core 层不存在 print/input", not leaks)

        ok("全程未导入 tui 层", "tui" not in sys.modules)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\ncore 层验证全部通过，共 {passed} 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
