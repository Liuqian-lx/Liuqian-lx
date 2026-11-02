# Agent_L

一个基于 Function Calling 的终端聊天助手：流式对话、工具调用闭环、对话历史持久化。
业务逻辑全部位于 `core/`，`tui/` 只负责渲染与事件转发。

## 目录结构

```
Agent_L/
├── main.py                 # 唯一入口：加载配置 -> 初始化会话 -> 启动 TUI
├── config.ini              # 模型与联网搜索配置
├── chat_history.json       # 对话历史（自动保存）
├── core/
│   ├── config.py           # config.ini 解析（LLM 配置 + 可选搜索配置）
│   ├── llm_client.py       # OpenAI 兼容流式客户端、tool_calls 聚合
│   ├── session.py          # 上下文维护、Skill 注入、工具闭环、历史读写
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

# 联网搜索配置；留空时 searchWeb 返回结构化提示，不影响其他功能
[search]
baidu_qianfan_api_key = <你的百度千帆 API Key>
```

- `[llm]` 为必填项，缺失时程序启动失败并提示。
- `[search]` 为可选项，缺失、为空或格式错误都不会中断程序。

## 工具列表

所有工具统一返回 `{"success": True, "result": ...}` 或
`{"success": False, "error": ...}`，由 `core/tools/__init__.py` 的
`execute_tool` 统一解析与分发。

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

## 验证

```bash
python verify_core.py
```

脚本不导入 `tui`、不发起真实网络请求，覆盖：配置读取、17 个工具注册与重名检查、
内置/文件工具、流式回调、工具闭环、历史加载/保存，以及 `searchWeb` 的
未配置 Key、空 query、网络异常、HTTP 错误、非法 JSON、结果归一化与空结果，
`fetchWebPage` 的空/非法 URL、curl 缺失/超时、网络失败、HTTP 4xx、
解析异常、空正文、8000 字符截断与 trafilatura 正文提取，
`RunCli` 的空命令、参数列表拼装、命令不存在、超时、系统错误、输出截断、
非 0 退出码与 `shell=True` 静态检查，
以及 Skill 扫描/Frontmatter 解析/重名与非法项跳过、system prompt 注入格式、
`loadSkill` 的 SKILL.md 与附件读取、路径穿越拦截、多匹配候选、Skill/文件不存在、
非 UTF-8 编码错误，`createSkill` 的名称校验、防覆盖、Frontmatter 规范化、
即时刷新与路径沙箱，以及 core 层无 `print`/`input` 静态检查。

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
