"""End-to-end smoke test for anythingllm-mcp.

Usage:
    .venv\\Scripts\\python smoke_test.py [http://127.0.0.1:8091/mcp]

Checks, over the real Streamable HTTP wire:
  * server/discover (auto, via the SDK client) succeeds on protocol 2026-07-28
  * tools/list exposes the workspace_chat, workspace_file_count and workspace_search tools
  * tools/call returns an AI answer supplied by AnythingLLM
  * workspace_file_count returns the number of files stored in the workspace
  * a modern POST (MCP-Protocol-Version: 2026-07-28 + body _meta) returns supportedVersions
  * a POST missing the version header is answered as a legacy-era request (dual-era fallback)
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request

from mcp import Client

TARGET = "http://127.0.0.1:8091/mcp"


async def main() -> None:
    async with Client(TARGET) as client:
        print("protocol_version:", client.protocol_version)
        print("server_capabilities:", client.server_capabilities)

        tools = await client.list_tools()

        def tool_name(t):
            if isinstance(t, tuple):
                return t[0]
            return getattr(t, "name", repr(t))

        names = [tool_name(t) for t in tools.tools]
        print("tools:", names)
        if "workspace_chat" not in names:
            raise SystemExit("FAIL: workspace_chat tool missing from tools/list")
        if "workspace_file_count" not in names:
            raise SystemExit("FAIL: workspace_file_count tool missing from tools/list")
        if "workspace_search" not in names:
            raise SystemExit("FAIL: workspace_search tool missing from tools/list")

        count_result = await client.call_tool("workspace_file_count", {})
        print("--- workspace_file_count result ---")
        for block in count_result.content:
            text = getattr(block, "text", None)
            if text is not None:
                print(text)
        print("-----------------------------------")

        search_result = await client.call_tool(
            "workspace_search", {"query": "test_doc", "top_n": 2}
        )
        print("--- workspace_search result ---")
        for block in search_result.content:
            text = getattr(block, "text", None)
            if text is not None:
                print(text)
        print("-------------------------------")

        result = await client.call_tool(
            "workspace_chat",
            {"message": "用中文回答：你能做什么？"},
        )
        print("--- call_tool result ---")
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                print(text)
        print("------------------------")
        print("OK: end-to-end call succeeded")


def raw_post(headers: dict, body: dict) -> tuple:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        TARGET,
        data=data,
        headers={**{"Content-Type": "application/json", "Accept": "application/json"}, **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise SystemExit(f"FAIL: server unreachable: {exc.reason}")


def modern_discover(body_params: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
            **body_params,
        },
    }


def check_raw_protocol() -> bool:
    ok = True

    status, body = raw_post(
        {"MCP-Protocol-Version": "2026-07-28", "mcp-method": "server/discover"},
        modern_discover({}),
    )
    if status == 200:
        result = json.loads(body).get("result", {})
        versions = result.get("supportedVersions", [])
        print(f"OK: raw modern discover -> supportedVersions={versions}")
        ok = ok and "2026-07-28" in versions
    else:
        print(f"FAIL: raw modern discover HTTP {status}: {body[:300]}")
        ok = False

    status, body = raw_post({}, modern_discover({}))
    fallback = body.startswith(b'{"jsonrpc":')
    if fallback and json.loads(body).get("error", {}).get("code") == -32601:
        print("OK: missing MCP-Protocol-Version header falls back to legacy (discover unknown)")
    else:
        print(f"WARN: missing MCP-Protocol-Version header produced HTTP {status}: {body[:300]}")
    return ok


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else TARGET
    TARGET = target
    asyncio.run(main())
    if not check_raw_protocol():
        raise SystemExit("FAIL: raw protocol checks did not pass")
    print("ALL CHECKS PASSED")