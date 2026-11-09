# AnythingLLM MCP Server

MCP Server（协议版本 **2026-07-28**，Streamable HTTP）把本机 AnythingLLM 封装为
MCP 工具。监听地址与端口由 `.env` 决定，当前配置为
`http://127.0.0.1:8091/mcp`。

## 提供的工具

| 工具 | 说明 | 依赖 LLM |
| --- | --- | --- |
| `workspace_chat` | 向工作区提问，由 AnythingLLM 基于工作区文档生成回答 | 是 |
| `workspace_file_count` | 返回工作区中的文件数量，可附带文件名列表 | 否 |
| `workspace_search` | 向量检索工作区文档，返回命中文档片段、来源文件名与相似度 | 否 |

工作区自动识别：AnythingLLM 只有一个工作区时自动选用；多个时通过 `.env` 的
`ANYTHINGLLM_WORKSPACE_SLUG` 指定。`workspace_chat` 使用固定的
`ANYTHINGLLM_SESSION_ID` 保持滚动对话历史。

> `workspace_chat` 需要 AnythingLLM 内配置好可用的 LLM 提供方（例如 LM Studio）。
> 模型未启动时它会返回 `Connection error`；仅检索资料请使用 `workspace_search`。

## 网页录入工具（upload.html）

> 独立的前端项目位于根目录 `AnythingLLMWebpage`（由 `serve.bat` 在
> `http://127.0.0.1:8092/index.html` 提供服务），其 `index.html` 即本目录
> `upload.html` 的副本；本目录保留一份便于随 MCP 服务一起分发。

浏览器打开 `upload.html` 即可把本地文档上传到 AnythingLLM 工作区并自动向量化
（`POST /api/v1/document/upload` + 轮询等待嵌入完成），之后即可用
`workspace_search` / `workspace_chat` 检索这些文档。

- 页面顶部填写 API 地址与 API Key（点击「保存并连接」后存入浏览器
  `localStorage`），默认地址 `http://localhost:3001/api`。
- 上传前请确保 AnythingLLM 正在运行。

## 快速开始

```powershell
# 1) 依赖（本机 Python 3.13 已安装 mcp / python-dotenv）
pip install -r requirements.txt

# 2) 配置
Copy-Item .env.example .env   # 填入 ANYTHINGLLM_API_KEY

# 3) 启动（确保 AnythingLLM 正在运行，端口 3001）
python server.py
```

Windows 下也可双击 `start.bat`：它使用绝对路径的 Python 与 `chcp.com`，
PATH 被裁剪时仍可启动；换机器时修改脚本顶部的 `PYTHON_EXE`。

启动后端点：`http://127.0.0.1:8091/mcp`。

> 目录里的 `.venv` 来自另一台机器（`pyvenv.cfg` 指向 `C:\Users\song\...`），
> 在本机不可用；`start.bat` 已改为使用系统 Python。如需重建：
> `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`。

## 验证

```powershell
# 端到端冒烟测试（discover / tools/list / tools/call / 头校验）
python smoke_test.py
```

## 接入 MCP 客户端

在 **项目工作目录** 的 `.mcp.json`（例如 `D:\Liuqian-lx\office\.mcp.json`）中：

```json
{
  "mcpServers": {
    "AnythingLLMMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8091/mcp"
    }
  }
}
```

本机推理（GGUF）单次 `workspace_chat` 可能需要数秒到数十秒，客户端超时请放宽。

## 配置项（`.env`）

| 变量 | 当前值 | 说明 |
|---|---|---|
| `ANYTHINGLLM_URL` | `http://localhost:3001/api` | AnythingLLM API 基地址 |
| `ANYTHINGLLM_API_KEY` | 必填 | Developer API key |
| `ANYTHINGLLM_WORKSPACE_SLUG` | 空（自动检测唯一工作区） | 指定工作区 |
| `ANYTHINGLLM_SESSION_ID` | `mcp-anythingllm-workspace` | 对话窗口 ID |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | `0.0.0.0` / `8091` / `/mcp` | MCP HTTP 监听 |
| `MCP_LOG_LEVEL` | `INFO` | 日志级别 |

## 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| `unreachable: [WinError 10061]` | AnythingLLM 未启动，确认 3001 端口可访问 |
| `HTTP 401 / No valid api key found` | API Key 无效，在设置中重新生成并更新 `.env` |
| `Multiple workspaces found` | 在 `.env` 设置 `ANYTHINGLLM_WORKSPACE_SLUG` |
| `chat error: Connection error` | AnythingLLM 内模型未启动，改用 `workspace_search` |
| `端口 8091 已被占用` | 先停止占用进程（`Get-NetTCPConnection -LocalPort 8091`）再启动 |

## 安全说明

- `.env` 已由 `.gitignore` 排除，API Key 不要提交到仓库。
- 如需仅本机访问，把 `MCP_HOST` 改为 `127.0.0.1`。
