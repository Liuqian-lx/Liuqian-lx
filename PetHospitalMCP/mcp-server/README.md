# 宠物医院 MCP 服务（`PetHospitalMCP/mcp-server`）

基于 `mcp` SDK 2.x（协议 2026-07-28）实现的宠物医院 MCP 服务，向
xAgent / Agent_L 等标准 MCP 客户端提供 `list_pets` / `create_pet` 工具。
数据直接读取本目录的 `data/pet.db`（PETDBv1 追加日志格式，当前 1011 条档案）。

> 本目录是宠物医院的 **Python 版 MCP 服务**（服务器名 `pet-hospital`），
> 与同一项目下的 `PetHospitalMCP/windows`（Go 版 REST 服务 + 网页控制台）
> 并列存放。
> AnythingLLM 知识库 MCP 服务在根目录的 `AnythingLLMMCP`，监听 8091。

## 依赖

- Python 3.10+
- `pip install -r requirements.txt`（`mcp>=2.0.0`、`pydantic>=2.0.0`）

## 启动

### 方式一：HTTP 模式（默认，供常驻接入）

双击 `start.bat`，或在本目录执行：

```bat
python main.py
```

`start.bat` 使用本机 Python 绝对路径
`C:\Users\lq\AppData\Local\Programs\Python\Python313\python.exe`，`chcp` 也使用
`%SystemRoot%\System32\chcp.com` 的绝对路径，PATH 被裁剪时仍可启动；换机器
修改脚本顶部的 `PYTHON_EXE`。

默认监听 `0.0.0.0:8090`，MCP 端点为 `http://127.0.0.1:8090/mcp`。
启动成功输出：

```text
[MCP] ==========================================
[MCP] 宠物医院 MCP 服务启动成功
[MCP] 传输模式：streamable-http
[MCP] 监听地址：0.0.0.0:8090
[MCP] MCP 端点：http://127.0.0.1:8090/mcp
[MCP] 工具：list_pets / create_pet
[MCP] ==========================================
```

可用参数 / 环境变量：

| 参数 | 环境变量 | 默认值 |
| --- | --- | --- |
| `--http` / `--stdio` | `MCP_TRANSPORT=http\|stdio` | `http` |
| `--host` | `MCP_HOST` | `0.0.0.0` |
| `--port` | `MCP_PORT` | `8090` |
| `--path` | `MCP_PATH` | `/mcp` |

端口被占用时会在监听前直接报错退出，不会静默卡住。

### 方式二：stdio 模式（由 MCP 客户端拉起）

```bat
python main.py --stdio
```

stdio 模式下 stdout 是协议通道，全部日志输出到 stderr。

## 接入 Agent_L

在 **项目工作目录** 的 `.mcp.json`（例如 `D:\Liuqian-lx\office\.mcp.json`）中：

```json
{
  "mcpServers": {
    "PetHospitalMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8090/mcp"
    }
  }
}
```

stdio 方式：

```json
{
  "mcpServers": {
    "PetHospitalMCP": {
      "type": "stdio",
      "command": "C:/Users/lq/AppData/Local/Programs/Python/Python313/python.exe",
      "args": ["D:/Liuqian-lx/PetHospitalMCP/mcp-server/main.py", "--stdio"],
      "cwd": "D:/Liuqian-lx/PetHospitalMCP/mcp-server"
    }
  }
}
```

## 说明

- 本服务按**当前工作目录**查找 `./data/pet.db`，因此请在本目录内执行
  `python main.py` 或双击 `start.bat`（脚本会自动 `cd /d "%~dp0"`）。
- 本服务直接读写 `PetHospitalMCP/mcp-server/data/pet.db`，与
  `PetHospitalMCP/windows/data/pet.db` 是两份独立副本，数据不会自动同步。
- `PetHospitalMCP/windows/pethospital.exe` 是 Go 编写的 REST 服务 + 网页控制台
  （默认 `127.0.0.1:8080`），只提供 `/api/v1/...` 接口，**不实现 MCP 协议**，
  不能直接通过 `.mcp.json` 接入；需要其业务能力时应由本 MCP 服务读写同一份
  数据，或另行代理 REST 接口。
- 端口规划：宠物医院 MCP 8090，AnythingLLM MCP 8091，AnythingLLM 本体 3001。
