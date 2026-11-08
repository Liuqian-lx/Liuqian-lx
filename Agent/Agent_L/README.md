# Agent_L

一个基于 Function Calling 的终端聊天助手：流式对话、工具调用闭环、对话历史持久化。
业务逻辑全部位于 `core/`，`tui/` 只负责渲染与事件转发。

## 目录结构

```
Agent_L/
├── main.py                 # 唯一入口：加载配置 -> 初始化会话 -> 启动 TUI
├── config.ini              # 模型与联网搜索配置
├── .mcp.json               # 外部 MCP 服务器配置（可选）
├── chat_history.json       # 对话历史（自动保存）
├── core/
│   ├── config.py           # config.ini 解析（LLM 配置 + 可选搜索配置）
│   ├── context_manager.py  # Token 统计、上下文归档与全文关键词检索
│   ├── llm_client.py       # OpenAI 兼容流式客户端、tool_calls 聚合、usage 采集
│   ├── session.py          # 上下文维护、压缩、Skill 注入、工具闭环、历史读写
│   ├── mcp/
│   │   ├── config.py       # .mcp.json 解析与校验
│   │   ├── client_manager.py # MCP 会话连接、工具发现、调用路由
│   │   └── tool_adapter.py # MCP 工具 -> Function Call Schema / 结果包装
│   ├── skills/
│   │   ├── loader.py       # .agents/skills 扫描与 Frontmatter 解析
│   │   └── manager.py      # Skill 生命周期、system prompt 段落生成
│   └── tools/
│       ├── __init__.py     # TOOLS / TOOL_MAP 汇总、execute_tool
│       ├── builtin.py      # 内置工具
│       ├── file_ops.py     # 文件操作工具
│       ├── web_search.py   # 联网搜索工具 searchWeb
│       ├── web_fetch.py    # 网页正文提取工具 fetchWebPage
│       ├── run_cli.py      # 命令行执行工具 RunCli
│       ├── recall_context.py # 上下文归档检索工具 recallContext
│       ├── skill_loader.py # 动态技能加载工具 loadSkill
│       └── create_skill.py # 技能创建工具 createSkill
├── tui/                    # Textual 界面层（不含业务逻辑）
├── verify_core.py          # core 层离线验证脚本
└── requirements.txt
```

## 环境与运行

```bash
pip install -r requirements.txt
python main.py
```

## 配置

`config.ini`：

```ini
[llm]
base_url = https://api.deepseek.com/v1
model_name = deepseek-flash
api_key = <你的大模型 API Key>

# 可选：模型上下文窗口大小（Token）。不填写时按 128k 估算，界面标注「默认」
# context_window = 128000

# 联网搜索配置；留空时 searchWeb 返回结构化提示，不影响其他功能
[search]
baidu_qianfan_api_key = <你的百度千帆 API Key>
```

- `[llm]` 为必填项，缺失时程序启动失败并提示。
- `[llm] context_window` 为可选项，用于上下文占用比例计算；缺失或非法时
  按 128k 兜底，并在 TUI 顶栏显示「默认」。
- `[search]` 为可选项，缺失、为空或格式错误都不会中断程序。

## 工具列表

所有工具统一返回 `{"success": True, "result": ...}` 或
`{"success": False, "error": ...}`，由 `core/tools/__init__.py` 的
`execute_tool` 统一解析与分发。除下表 19 个本地工具外，`.mcp.json`
中配置的 MCP 服务器工具也会在启动时动态合并进来（见「外部 MCP 工具」）。

| 工具名 | 用途 | 参数 |
| --- | --- | --- |
| `getDate` | 获取本机当前日期与时间 | 无 |
| `isLeapYear` | 判断年份是否为闰年 | `year`（integer，必填） |
| `get_current_directory` | 获取当前工作目录 | 无 |
| `list_directory` | 列出目录内容 | `dir_path`（string，可选） |
| `get_file_type` | 判断路径是文件还是目录 | `file_path`（string，必填） |
| `read_file_content` | 读取 UTF-8 文本文件 | `file_path`（string，必填） |
| `create_file` | 创建文件 | `dir_path`、`file_name`（必填），`content`（可选） |
| `edit_file` | 覆盖或追加写入文件 | `file_path`、`content`（必填），`mode`（可选） |
| `create_directory` | 创建目录（支持多级） | `dir_path`（string，必填） |
| `remove_directory` | 递归删除目录 | `dir_path`（string，必填） |
| `remove_file` | 删除单个文件 | `file_path`（string，必填） |
| `rename_path` | 重命名文件或目录 | `old_path`、`new_name`（必填） |
| `searchWeb` | 联网搜索最新公开信息 | `query`（string，必填） |
| `fetchWebPage` | 抓取网页正文并转换为 Markdown | `url`（string，必填） |
| `RunCli` | 执行本地已安装的命令行程序 | `command`（string，必填），`args`（string 数组，可选） |
| `loadSkill` | 按需加载 Skill 的 SKILL.md 或附件 | `name`（string，必填），`filename`（string，可选） |
| `createSkill` | 根据内容创建新 Skill | `name`（string，必填），`skillContext`（string，必填） |
| `createMCP` | 新增/更新 MCP 服务器配置并热重载 | `name`、`type`、`url`（必填），`command`、`args`、`env`、`cwd`、`headers`（可选） |
| `recallContext` | 在上下文压缩归档中检索历史原文 | `text`（string，必填），`id`（string，可选） |

### searchWeb（联网搜索）

- **名称**：`searchWeb`
- **用途**：联网搜索互联网上的最新公开信息，返回相关网页的标题、URL 链接和内容摘要；
  适合时事新闻、最新数据、近期事件、模型训练截止后的新信息。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `query` | string | 是 | 搜索关键词或问题 |

- **配置**：在 `config.ini` 的 `[search]` 小节填写
  `baidu_qianfan_api_key`。Key 只从配置文件读取，代码中不硬编码。
  未配置时返回：
  `{"success": False, "error": "未配置百度千帆搜索 API Key，请在 config.ini 的 [search] 小节填写 baidu_qianfan_api_key"}`。
- **接口**：百度千帆「百度AI搜索」
  `POST https://qianfan.baidubce.com/v2/ai_search/web_search`，
  鉴权头 `Authorization: Bearer <API Key>`，超时 10 秒，
  使用 Python 标准库 `urllib`，无需新增依赖。
- **返回格式**：

  ```text
  搜索「<query>」共找到 N 条参考结果：
  1. 标题：<title>
     链接：<url>
     摘要：<summary>
  2. ...
  ```

  结果为空时返回 `{"success": True, "result": "未检索到相关结果，请更换关键词后重试"}`。
  网络失败、HTTP 非 200、响应格式异常、空 query 等均返回中文结构化错误，
  不会抛异常中断会话。

### fetchWebPage（网页正文提取）

- **名称**：`fetchWebPage`
- **用途**：抓取指定网页的正文并转换为 Markdown，保留标题、段落、列表、表格和超链接，
  自动去除导航栏、广告、页脚、侧边栏等无关内容；适合阅读、总结或提取网页正文。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `url` | string | 是 | 目标网页地址，必须以 `http://` 或 `https://` 开头 |

- **实现方式**：
  - 通过 `subprocess.run(["curl", ...])` 调用本地 curl，参数列表执行，
    不使用 `shell=True`；curl 与 subprocess 均设置 15 秒超时，并附带浏览器 User-Agent。
  - 使用 `trafilatura` 提取正文并输出 Markdown（`include_formatting`、
    `include_links`、`include_tables`），优先精度模式以去除页面噪声。
  - 正文超过 8000 字符时截断，并在末尾标注「正文已截断」。
- **返回格式**：

  ```json
  {
    "success": true,
    "result": {
      "url": "https://example.com",
      "markdown": "# 页面标题\n\n正文……"
    }
  }
  ```

- **异常处理**：空/非法 URL、本地缺少 curl、网络或 DNS 失败、超时、HTTP 4xx/5xx、
  trafilatura 提取异常、正文为空，均返回中文结构化错误，不会中断会话。

### RunCli（命令行执行）

- **名称**：`RunCli`
- **用途**：调用本地已安装的任意 CLI 程序（如 `python`、`git`、`dir`、`curl`），
  返回退出码、标准输出和标准错误；适合需要本机命令配合的任务。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `command` | string | 是 | 可执行程序名称 |
  | `args` | string 数组 | 否 | 程序参数列表，默认空数组 |

- **实现方式**：
  - 使用 `subprocess.run([command, *args], shell=False, ...)`，
    程序名与参数以列表方式传入，**绝不使用 `shell=True`**，也不拼接 shell 字符串；
  - 单次执行超时 30 秒；
  - `stdout`、`stderr` 分别截断到前 4000 字符，超出部分标注「...输出已截断」。
- **返回格式**：命令只要正常跑完（含非 0 退出码）都返回 `success=true`，
  由模型根据 `exit_code` 判断执行结果：

  ```json
  {
    "success": true,
    "result": {
      "command": "git",
      "args": ["--version"],
      "exit_code": 0,
      "stdout": "...",
      "stderr": "..."
    }
  }
  ```

- **异常处理**：空命令、命令不存在、执行超时、权限不足等系统错误均返回中文结构化错误，
  不会中断会话。
- **安全说明**：本阶段按教学要求不实现命令白名单/黑名单或人工审批，命令以运行 Agent
  的当前用户权限执行；仅适用于受控的教学实验环境，切勿在不可信输入或生产环境中开放。

## 外部 MCP 工具（MCP Client）

程序启动时会读取**当前工作目录**下的 `.mcp.json`，连接其中配置的 MCP
服务器，调用标准 `list_tools()` 获取工具列表，并转换为与本地工具完全一致的
Function Calling Schema 后合并进 `TOOLS` / `TOOL_MAP`。所有 MCP 代码位于
`core/mcp/`，`tui/` 无任何改动。

### 配置文件

```json
{
  "mcpServers": {
    "Bazi-MCP": {
      "type": "streamable_http",
      "url": "https://mcp.api-inference.modelscope.net/4a3222faa31a4e/mcp"
    },
    "PetHospitalMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8090/mcp"
    },
    "AnythingLLMMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8091/mcp"
    },
    "LocalFiles": {
      "type": "stdio",
      "command": "python",
      "args": ["server.py"],
      "env": {"API_KEY": "..."},
      "cwd": "."
    }
  }
}
```

- `type` 支持 `streamable_http`（需要 `url`）和 `stdio`（需要 `command`，
  可选 `args` / `env` / `cwd`）；缺省时按 `command` / `url` 自动推断。
- 支持 `headers`（HTTP 鉴权头）等标准字段；URL 首尾空白会被自动去除。
- 文件不存在时静默跳过；JSON 损坏或单条配置不完整时只跳过对应条目，
  不影响程序启动。
- 配套的本地宠物医院 MCP 服务（`anytingLLMMCP` 目录，提供 `list_pets` /
  `create_pet`）需先启动：运行其 `start.bat` 或 `python main.py`，默认监听
  `0.0.0.0:8090`，端点为 `/mcp`。也可改用 stdio 配置由 Agent 直接拉起
  （`python main.py --stdio`），无需常驻进程。
- AnythingLLM 知识库 MCP 服务（`111/anythingllm-mcp`，提供 `workspace_chat` /
  `workspace_file_count` / `workspace_search`）监听 `0.0.0.0:8091`，端点为
  `/mcp`；其 `workspace_search` 是纯向量检索，不依赖聊天模型。
- `D:\Liuqian-lx\PetHospitalMCP\windows\pethospital.exe` 是 Go 编写的 REST 服务
  （默认 `127.0.0.1:8080`，网页界面 `/`、接口清单 `/api/v1/endpoints`），
  **不实现 MCP 协议**，不要写入 `mcpServers`。
- Python 版（`anytingLLMMCP`）与 exe 版使用**两份独立的 `data/pet.db` 副本**，
  数据不会自动同步；MCP 能力统一由 Python 版提供。
- 除手工编辑外，也可在会话中调用 `createMCP` 工具动态新增/更新服务器配置，
  写入后自动热重载（见「createMCP 工具」）。

### 工具命名与调用

- 工具名直接沿用 MCP 服务器返回的名称。
- 若**不同服务器存在同名工具**，或 MCP 工具与本地工具重名，对外暴露名
  自动变为 `服务器名_工具名`（例如 `AnythingLLMMCP_list_pets`）；内部保留
  原始工具名，调用时自动还原。
- 参数 Schema 由 MCP `inputSchema` 转换而来，与本地工具风格一致。
- 调用结果统一包装为 `{"success": True, "result": ...}` /
  `{"success": False, "error": ...}`，兼容文本内容、结构化数据与错误信息。

### 容错

- 单个服务器连接失败 → 跳过该服务器，错误记录在 `get_mcp_manager().errors`；
- 所有服务器都连接失败或未配置 → Agent 退化为纯本地工具模式，功能不受影响；
- 所有连接与调用异常都会被捕获并作为工具结果返回给模型，程序不会崩溃；
- 如需完全禁用 MCP（例如离线验证），设置环境变量 `AGENT_L_DISABLE_MCP=1`。

## 动态 Skills（Agent Skills）

Agent 启动时会扫描项目根目录下的 `.agents/skills/`，把每个一级子目录视为一个 Skill。
这里的「项目根目录」是**启动程序时的工作目录（`os.getcwd()`）**，
因此建议在 `Agent_L` 目录下启动：

```bash
cd Agent_L
python main.py
```

### 目录约定

```text
<启动目录>/
└── .agents/
    └── skills/
        ├── pdf/
        │   ├── SKILL.md          # 必需，YAML Frontmatter + 正文
        │   ├── references/       # 可选附件
        │   │   └── syntax.md
        │   └── scripts/
        │       └── parse.py
        └── writer/
            └── SKILL.md
```

`SKILL.md` 必须以 Frontmatter 开头，并包含 `name` 与 `description`：

```markdown
---
name: pdf
description: 处理 PDF 文档的读取、拆分与内容摘要
---

# PDF Skill

这里是完整的使用说明……
```

扫描规则与异常处理：

- `.agents/skills/` 不存在时静默跳过，不影响启动；
- 子目录没有 `SKILL.md`、Frontmatter 缺失、缺少 `name`/`description`：静默跳过；
- `name` 重复时保留目录名排序后的第一个，后续重名项跳过；
- 初始化阶段**只读取 Frontmatter 中的 name/description**，不读取正文与附件。

### System Prompt 注入

发现 Skill 后，会话初始化阶段会在 system prompt 末尾追加：

```text
## 可用 Skills

当前项目发现以下 Skill。Skill 的完整内容不会预先载入上下文，
当用户任务与某个 Skill 的描述匹配时，请调用 loadSkill 工具加载详细内容。
只传 name 会读取该 Skill 的 SKILL.md 全文；需要附件时再传 filename 指定文件。

- pdf: 处理 PDF 文档的读取、拆分与内容摘要
- writer: 写作与润色助手
```

没有可用 Skill 时不会注入任何 system 消息，原有消息结构保持不变。
系统提示只在请求时前置，不会写入 `chat_history.json`。

### loadSkill 工具

- **名称**：`loadSkill`
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `name` | string | 是 | Skill 名称 |
  | `filename` | string | 否 | 附件文件路径或名称；省略时读取 `SKILL.md` 全文 |

- **路径解析顺序**：
  1. 绝对路径：规范化后校验是否位于该 Skill 目录内部；
  2. 相对路径：与 Skill 目录拼接后校验；
  3. 仅文件名：在 Skill 目录内递归搜索，唯一匹配直接读取，多个匹配返回候选路径列表。
- **安全沙箱**：所有路径经 `os.path.realpath` 规范化，并用 `os.path.commonpath`
  校验最终路径必须落在 Skill 目录内部；`../`、目录外绝对路径与指向外部的符号链接
  都会被拦截，返回 `"路径超出 Skill 目录范围，禁止访问"`。
- **返回格式**：

  ```json
  {"success": true, "result": {"skill_name": "pdf", "file": "SKILL.md", "content": "全文内容"}}
  ```

  ```json
  {"success": true, "result": {"skill_name": "pdf", "file": "references/syntax.md", "content": "..."}}
  ```

  ```json
  {"success": true, "result": {"skill_name": "pdf", "matches": [".../a/intro.md", ".../b/intro.md"], "hint": "存在多个匹配文件，请指定完整路径"}}
  ```

- **异常处理**：Skill 不存在、文件不存在、非 UTF-8 文件、读取失败均返回中文结构化错误，
  不会中断会话。

### createSkill 工具

- **名称**：`createSkill`
- **用途**：根据自然语言把一套方法或知识固化为新的 Skill，写入
  `<工作目录>/.agents/skills/<name>/SKILL.md`。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `name` | string | 是 | Skill 名称，kebab-case 格式 |
  | `skillContext` | string | 是 | 写入 `SKILL.md` 的完整内容，可包含 YAML Frontmatter |

- **名称校验**：仅允许小写字母、数字和连字符，不能为空，也不能以连字符开头或结尾；
  不合法时返回 `"Skill 名称不合法，仅允许小写字母、数字和连字符（kebab-case 格式）"`。
- **防覆盖**：目标目录已存在时直接返回
  `"Skill <name> 已存在，禁止覆盖原有内容"`，不执行任何写入。
- **安全沙箱**：最终路径经 `os.path.realpath` 规范化，并用 `os.path.commonpath`
  校验必须落在 `<工作目录>/.agents/skills/` 内部，越界时返回
  `"路径超出 Skill 目录范围，禁止创建"`。
- **Frontmatter 规范化**：
  - 内容没有 Frontmatter 时，自动生成 `name` 与 `description` 头部，
    `description` 取正文前 80 字符；
  - 已有 Frontmatter 时，补全缺失的 `name`/`description`，保留其他字段，
    `name` 统一修正为传入的标准名称。
- **返回格式**：

  ```json
  {"success": true, "result": {"skill_name": "pdf-tools", "skill_path": ".agents/skills/pdf-tools", "file": "SKILL.md", "message": "Skill 创建成功，已可被加载使用"}}
  ```

- **即时生效**：创建成功后刷新当前 `SkillManager`，同一会话内可直接用 `loadSkill` 读取。

Skill 能力全部使用 Python 标准库实现，未新增第三方依赖；`tui/` 目录不受影响。

### createMCP 工具

- **名称**：`createMCP`
- **用途**：把用户提供的 MCP 服务器配置写入**当前工作目录**的 `.mcp.json`，
  支持下述两种协议；同名服务器会被覆盖更新，其他服务器保持不变。写入成功后
  立即重载 MCP 管理器，新服务器的工具在同一会话的下一轮请求中即可使用，
  **无需重启程序**。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `name` | string | 是 | 服务器名称，字母/数字/点/下划线/连字符，1-64 字符 |
  | `type` | string | 是 | `streamable_http` 或 `stdio`（兼容 `http`/`streamable-http` 写法） |
  | `url` | string | 是 | MCP 服务地址；`stdio` 类型传空字符串 |
  | `command` | string | 否 | `stdio` 类型必填，可执行程序 |
  | `args` | string[] | 否 | `stdio` 类型的程序参数 |
  | `env` | object | 否 | `stdio` 类型的环境变量 |
  | `cwd` | string | 否 | `stdio` 类型的工作目录 |
  | `headers` | object | 否 | `streamable_http` 类型的请求头 |

- **安全校验**：
  - 名称非法、协议类型不支持、HTTP 地址不是 `http(s)://`、`stdio` 缺少
    `command` 时均返回结构化错误；
  - 只写当前工作目录下的 `.mcp.json`，符号链接指向目录外时拒绝写入；
  - 已有配置不是合法 JSON 或结构错误时**拒绝覆盖**，避免损坏用户配置；
  - 采用临时文件 + `os.replace` 原子写入，失败不会留下半个文件。
- **返回格式**：

  ```json
  {"success": true, "result": {"name": "PetHospitalMCP", "type": "streamable_http", "action": "created", "config_path": "...\\.mcp.json", "mcp_tool_count": 5, "mcp_tools": ["list_pets", "create_pet"], "mcp_errors": [], "message": "..."}}
  ```

- **热重载**：`core/tools/refresh_mcp_tools()` 关闭旧连接、重新读取配置、
  发现工具，并同步更新 `TOOLS` / `TOOL_MAP` 与已创建的 `ChatSession`
  （不修改 `session.py`）。

## 上下文压缩与历史检索

长时间任务会不断累积对话历史，最终占满模型上下文窗口。本功能采用
**「原始上下文归档 + LLM 摘要压缩 + 本地关键词检索」** 的简单方案，
不使用向量数据库或 Embedding，全部由 Python 标准库实现。

### 1. 顶栏上下文使用量

TUI 顶部栏醒目位置实时显示：

```text
上下文 32.4k / 128k（默认） · 25.3%
```

- `32.4k`：当前会话已占用的 Token（System Prompt + 用户消息 + 对话历史 +
  工具调用与工具结果 + 工具定义）；
- `128k`：模型上下文窗口；读取 `config.ini` 的 `context_window`，
  未配置或无法获取时按 128k 兜底，并显示「默认」二字；
- `25.3%`：占用百分比。

Token 统计优先使用模型 API 在流式响应末尾返回的 `usage`
（请求时自动带上 `stream_options.include_usage`，兼容接口不支持时会自动重试），
取不到时按「英文约 4 字符 1 Token、中文 1 字符 1 Token」估算。

每次 LLM 响应后都会刷新。达到窗口的 **60%** 时：

- 界面显示黄色警告，提示执行 `/compact`；
- 输入框占位文字切换为压缩提示；
- xAgent 拒绝新的普通提示词（core 层同样会拒绝），直到压缩成功完成。

### 2. `/compact` 手动压缩

在输入框输入 `/compact` 并回车即可触发。压缩开始后：

- 进入专门的压缩状态，输入框禁用，不会处理原任务；
- **不执行任何 Function Calling 工具**，只调用 LLM 生成摘要；
- 保存归档、替换上下文、写入历史等操作由 `ChatSession` 完成。

执行流程：

1. **保存原始上下文**：把当前 `messages` 逐行写入
   `<项目根>/.agents/context/<编号>.jsonl`，编号形如 `20261022-153000`，
   同一秒冲突时追加 `-1`、`-2`。每行是一条原始消息，保留 `role`、
   `content`、`tool_calls` 参数、`tool_call_id`、工具返回结果与消息顺序。
   写入采用临时文件 + `os.replace` 原子替换；**保存成功后才继续压缩**。
2. **调用 LLM 生成摘要**：使用 `core/context_manager.py` 中的
   `COMPACTION_SYSTEM_PROMPT`（上下文管理助手 Prompt），要求输出约
   5,000 Tokens 的 Markdown 工作摘要。该次调用**不传 tools**，即使模型
   返回 `tool_calls` 也会被忽略。
3. **替换上下文**：历史消息被替换为一条摘要消息；System Prompt 与工具
   定义保持不变。摘要末尾自动追加归档说明：

   ```text
   此前上下文已于 2026-10-22 15:30:00 完成压缩，原始上下文保存在编号为
   20261022-153000 的归档文件中。如需查找历史信息，请使用 recallContext 工具。
   ```

4. **展示对比面板**：成功后弹出浮动面板，左栏为压缩前原文，右栏为压缩后
   摘要，两栏独立滚动，右下角「关闭」按钮或 `Esc` 退出。原文超过 6 万字符
   时面板只展示前 6 万字符，完整内容已写入归档。
5. **解除限制**：成功后恢复输入；失败时保留原有上下文、提示错误，并允许
   重新执行 `/compact`。

### 3. recallContext 工具

- **名称**：`recallContext`
- **用途**：当 LLM 发现压缩摘要缺少历史细节时，主动检索原始归档。
- **参数**：

  | 参数 | 类型 | 必填 | 说明 |
  | --- | --- | --- | --- |
  | `text` | string | 是 | 关键词或文本内容；多个词以空格分隔时要求全部命中 |
  | `id` | string | 否 | 指定归档编号；省略时检索 `.agents/context/` 下全部归档 |

- **检索方式**：逐行读取 JSONL，对 `role`、`content`、工具名、工具调用参数、
  `tool_call_id`、工具结果做大小写不敏感的全文关键词匹配。
- **返回内容**：归档编号、行号、角色、命中次数与命中位置附近的原文片段；
  最多返回 10 条，每条片段最多 400 字符，总长度控制在 4,000 字符以内，
  避免检索结果再次占满上下文。
- **返回示例**：

  ```json
  {
    "success": true,
    "result": {
      "query": "alpha.txt",
      "archive_id": "all",
      "archive_count": 2,
      "total_matches": 3,
      "returned": 3,
      "truncated": false,
      "matches": [
        {
          "archive_id": "20261022-153000",
          "line": 2,
          "role": "assistant",
          "score": 1,
          "snippet": "tool_call id=call_1 name=read_file_content arguments={\"file_path\": \"alpha.txt\"}"
        }
      ]
    }
  }
  ```

- **错误处理**：空关键词、非法归档编号（含路径穿越）、归档不存在均返回
  中文结构化错误，不会中断会话。

该工具与其他本地工具一样注册在 `TOOLS` / `TOOL_MAP` 中，压缩后的摘要末尾
会主动提示模型使用它。

## 验证

```bash
python verify_core.py
```

脚本不导入 `tui`、不发起真实网络请求，覆盖：配置读取（含可选
`context_window`）、19 个工具注册与重名检查、内置/文件工具、流式回调、
工具闭环、历史加载/保存，以及 `searchWeb` 的
未配置 Key、空 query、网络异常、HTTP 错误、非法 JSON、结果归一化与空结果，
`fetchWebPage` 的空/非法 URL、curl 缺失/超时、网络失败、HTTP 4xx、
解析异常、空正文、8000 字符截断与 trafilatura 正文提取，
`RunCli` 的空命令、参数列表拼装、命令不存在、超时、系统错误、输出截断、
非 0 退出码与 `shell=True` 静态检查，
以及 Skill 扫描/Frontmatter 解析/重名与非法项跳过、system prompt 注入格式、
`loadSkill` 的 SKILL.md 与附件读取、路径穿越拦截、多匹配候选、Skill/文件不存在、
非 UTF-8 编码错误，`createSkill` 的名称校验、防覆盖、Frontmatter 规范化、
即时刷新与路径沙箱，`createMCP` 的配置写入/覆盖/异常拒绝，以及
上下文 Token 估算与 128k 默认窗口、API usage 优先、JSONL 归档格式、
`/compact` 压缩替换与失败保留原上下文、60% 阈值拦截、`recallContext`
的全文检索与参数校验，最后执行 core 层无 `print`/`input` 静态检查。

### 示例 Skill 测试步骤

在 `Agent_L` 目录下创建示例 Skill，然后启动程序：

```bash
cd Agent_L

mkdir -p .agents/skills/pdf/references
cat > .agents/skills/pdf/SKILL.md <<'EOF'
---
name: pdf
description: 处理 PDF 文档的读取、拆分与内容摘要
---

# PDF Skill

处理 PDF 时优先使用 RunCli 调用本地工具，输出前检查文件路径。
详细参数见 references/syntax.md。
EOF

printf '# PDF 参数速查\n\n- --pages: 指定页码\n' > .agents/skills/pdf/references/syntax.md

python main.py
```

在界面中依次提问：

1. 「你现在有哪些 Skill？」——模型应能从 system prompt 中看到 `pdf` 及其描述；
2. 「加载 pdf 这个 Skill 的完整说明」——模型调用
   `loadSkill({"name": "pdf"})`，返回 `SKILL.md` 全文；
3. 「读取 pdf Skill 里的 references/syntax.md」——模型调用
   `loadSkill({"name": "pdf", "filename": "references/syntax.md"})`。

也可以不启动界面，直接验证工具：

```bash
python -c "import json; from core.skills import SkillManager, set_active_manager; from core.tools import execute_tool; set_active_manager(SkillManager('.')); print(json.dumps(execute_tool('loadSkill', json.dumps({'name': 'pdf'})), ensure_ascii=False, indent=2))"
```

把 `filename` 换成 `../config.ini` 再执行，应返回
`{"success": false, "error": "路径超出 Skill 目录范围，禁止访问"}`。

### 联网搜索实测

确认 `config.ini` 的 `[search]` 已填写真实 Key 后：

```bash
cd Agent_L
python -c "from core.tools.web_search import searchWeb; print(searchWeb('今天的科技新闻'))"
```

或直接运行 `python main.py`，在界面中提问「最近有什么科技新闻？」，
模型会自动调用 `searchWeb`。

验证未配置路径时，把 `baidu_qianfan_api_key` 留空并重新提问即可。

### 网页正文提取实测

确认本地可执行 `curl`，并已安装依赖：

```bash
pip install -r requirements.txt
cd Agent_L
python -c "from core.tools.web_fetch import fetchWebPage; import json; print(json.dumps(fetchWebPage('https://example.com'), ensure_ascii=False, indent=2))"
```

或运行 `python main.py`，发送一条带链接的消息，例如
「帮我总结一下 https://example.com 的内容」，模型会调用 `fetchWebPage`。
