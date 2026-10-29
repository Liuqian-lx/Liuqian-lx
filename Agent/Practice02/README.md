# Practice02 —— 文件操作 AI Agent

## 一、项目简介

本项目是一个基于 **function call（工具调用）** 的**文件操作 AI Agent**。

它把大模型的工具调用能力与本地文件系统操作结合起来：用户用自然语言下达指令，大模型自主决定调用哪个工具、传什么参数，程序在本地真实执行文件操作，再把执行结果回填给大模型，由大模型生成最终的自然语言答复。

整个过程中，**大模型只负责"决策"与"表达"，不直接接触文件；所有实际的文件读写都由本地 Python 代码完成**。

### 工作流程

1. 用户在命令行输入自然语言指令，例如：`看看当前目录下有哪些文件`；
2. 程序在请求中附带全部工具的 JSON Schema（`tools=TOOLS`）；
3. 大模型判断需要调用哪个工具及参数，以 `tool_calls` 形式返回；
4. 程序按工具名分发，在本地执行对应函数；
5. 执行结果以 `role: "tool"` + `tool_call_id` 回填上下文，**二次请求**大模型；
6. 大模型基于真实执行结果生成回答，流式打印到终端。

### 主要特性

- **流式输出**：回答逐字打印，无需等待完整响应；
- **统一返回格式**：所有工具返回 `{"success": True, "result": ...}` 或 `{"success": False, "error": ...}`；
- **注册式扩展**：新增工具只需在 `TOOLS` 加 Schema、在 `TOOL_MAP` 加映射，主程序无需改动；
- **会话持久化**：对话历史保存到 `chat_history.json`，下次启动自动恢复；
- **内置自测**：工具模块自带 50+ 项断言，可脱离大模型独立验证。

---

## 二、文件结构

```
Practice02/
├── chat.py                 # 主程序
├── file_agent_tools.py     # 文件操作工具模块
├── config.ini              # 大模型配置
├── chat_history.json       # 对话历史
├── arch.mmd                # Mermaid 架构图源文件
├── Mermaid.png             # 架构图导出图片
├── test_lm.py              # 模型连通性测试脚本
└── README.md               # 本说明文档
```

### 核心文件及作用

| 文件 | 作用 |
| --- | --- |
| `chat.py` | **主程序**。读取配置、维护 `messages` 上下文、流式调用大模型、聚合 `delta.content` 与 `delta.tool_calls`、按工具名分发执行、回填结果并二次请求。同时内置 `getDate`、`isLeapYear` 两个工具。 |
| `file_agent_tools.py` | **工具模块**。10 个文件操作工具的 JSON Schema（`TOOLS`）与具体实现（`TOOL_MAP`），纯本地能力层，不依赖大模型；附带 `run_selftest()` 自测。 |
| `config.ini` | **大模型配置**。`[llm]` 段保存 `base_url`、`model_name`、`api_key` 三项。 |
| `chat_history.json` | **对话历史**。保存完整 `messages` 列表，实现跨会话记忆，退出时自动写入。 |
| `arch.mmd` | **架构图源文件**。Mermaid `flowchart TD` 语法，描述各层调用关系。 |
| `Mermaid.png` | **架构图导出图片**。`arch.mmd` 渲染后的静态图片，便于快速查看。 |
| `test_lm.py` | **连通性测试脚本**。独立验证模型服务地址与密钥是否可用。 |

---

## 三、10 个文件操作工具

以下工具均定义在 `file_agent_tools.py` 中，通过 `TOOL_MAP` 注册给主程序分发调用。

### 读取与查询类

| # | 工具名 | 功能说明 | 主要参数 |
| --- | --- | --- | --- |
| 1 | `get_current_directory` | 获取当前工作目录的绝对路径 | 无 |
| 2 | `list_directory` | 列出指定目录下所有文件与子目录，并标注每一项是"文件"还是"目录" | `dir_path`（可选，默认当前目录） |
| 3 | `get_file_type` | 判断路径是文件还是目录。文件返回扩展名，无扩展名返回"无扩展名"，目录返回 `directory` | `file_path` |
| 4 | `read_file_content` | 以 UTF-8 读取纯文本文件全文；非 UTF-8 或二进制文件返回错误 | `file_path` |

### 创建与编辑类

| # | 工具名 | 功能说明 | 主要参数 |
| --- | --- | --- | --- |
| 5 | `create_file` | 在指定目录下创建新文件，可写入初始内容；父目录必须已存在，文件已存在时**不会覆盖** | `dir_path`、`file_name`、`content`（可选） |
| 6 | `edit_file` | 编辑已存在的文本文件。`mode=overwrite` 覆盖全部内容，`mode=append` 追加到末尾 | `file_path`、`content`、`mode`（可选，默认 `overwrite`） |
| 7 | `create_directory` | 创建目录，支持多级嵌套路径（如 `a/b/c`）；目录已存在时返回错误 | `dir_path` |

### 删除与重命名类

| # | 工具名 | 功能说明 | 主要参数 |
| --- | --- | --- | --- |
| 8 | `remove_directory` | 删除目录；**非空目录会被递归删除**，请谨慎使用 | `dir_path` |
| 9 | `remove_file` | 删除单个文件；若目标是目录则返回错误 | `file_path` |
| 10 | `rename_path` | 重命名文件或目录，只改名称不改变所在位置；新名称已存在时返回错误 | `old_path`、`new_name` |

### 附：chat.py 内置工具

| 工具名 | 功能说明 |
| --- | --- |
| `getDate` | 获取本机当前系统日期与时间（调用 `cmd /c date /t` 与 `time /t`） |
| `isLeapYear` | 判断指定年份是否为闰年 |

---

## 四、运行方式

### 环境准备

- **Python 3.8+**
- 安装依赖：

```bash
pip install openai
```

- 操作系统：文件工具与 `getDate` 基于 Windows 路径与 `cmd` 命令实现，**建议在 Windows 下运行**。

### 配置大模型

编辑 `config.ini`，填入可用的 OpenAI 兼容服务信息：

```ini
[llm]
base_url = https://api.deepseek.com/v1
model_name = deepseek-flash
api_key = sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ `config.ini` 中含明文 API Key，请勿将真实密钥提交到公开仓库。

### 启动对话

在项目目录下执行：

```bash
python chat.py
```

看到 `请输入提示词：` 后即可用自然语言下达指令，例如：

```
请输入提示词：看看当前目录下有哪些文件
请输入提示词：帮我新建一个 demo.txt，内容写"hello agent"
请输入提示词：把 demo.txt 改名为 test.txt
请输入提示词：读取 test.txt 的内容
请输入提示词：今年是闰年吗
```

按 `Ctrl+C`（或 `Ctrl+Z` 回车）退出，对话历史会**自动保存**到 `chat_history.json`。

### 运行工具自测

无需调用大模型，直接验证 10 个文件工具的全部行为：

```bash
python file_agent_tools.py
```

输出示例：

```
[通过] get_current_directory 返回绝对路径
[通过] create_directory 创建目录
...
全部自测通过，共 52 项断言。
```

自测会在当前目录下临时创建 `_file_agent_selftest` 目录，**结束后自动清理**，不会污染项目目录。

### 测试模型连通性（可选）

若使用 LM Studio 等本地服务，先修改 `test_lm.py` 中的 `base_url` 与 `model`，再执行：

```bash
python test_lm.py
```

返回一句中文回复即说明服务可用。

---

## 五、架构图说明

架构图源文件为 **`arch.mmd`**，采用 Mermaid `flowchart TD`（自上而下）语法。

### 查看方式

可直接在 **[mermaid.live](https://mermaid.live)** 中查看：打开站点后，把 `arch.mmd` 的全部内容粘贴到左侧代码区，右侧即可实时渲染出架构图。

也可以在 VS Code（安装 Mermaid 插件）、Typora、GitHub 等支持 Mermaid 的环境中直接预览。此外目录下提供了渲染好的静态图片 `Mermaid.png`，可快速查看。

### 图中的分层

| 层级 | 说明 |
| --- | --- |
| **命令行交互层** | 用户输入、`input` 读取、终端流式打印、历史落盘 |
| **主程序 chat.py** | 主循环、配置加载、历史恢复、`chat()` 核心函数、流式聚合、工具分发、结果封装 |
| **大模型服务** | OpenAI 兼容接口 `client.chat.completions.create`，以及 `messages` 上下文 |
| **内置工具** | `getDate`、`isLeapYear`（含 `is_leap_year` 判定逻辑） |
| **工具模块** | `TOOLS` Schema 注册表、`TOOL_MAP` 分发表，以及分组后的 10 个文件工具 |
| **操作系统层** | 标准库 `os`/`os.path`、`shutil`、`subprocess`、Windows `cmd`、本地文件系统 |

### 关键调用链路

1. **对话启动**：`用户 → input → main 主循环 → chat()`；`load_config` 提供连接参数，`load_history` 恢复上下文。
2. **首次请求**：`chat() → API`，请求体携带 `messages` 与 `tools=TOOLS`（工具描述由此注入）。
3. **流式处理**：`API → 聚合 delta.content 与 delta.tool_calls`；纯文本直接 `print`，无工具调用则回复入上下文等待下一轮。
4. **工具分发**：出现 `tool_calls` 后按 `function.name` 路由 —— `getDate`/`isLeapYear` 走内置工具，命中 `TOOL_MAP` 走对应的文件工具。
5. **结果回填**：工具输出统一封装，以 `role: "tool"` + `tool_call_id` 回填 `messages`，由 `chat()` 携带结果**二次请求** `API`。
6. **最终回答**：模型基于真实执行结果生成答复，流式打印并存入历史。
7. **落盘**：退出时 `save_history` 将完整 `messages` 写入 `chat_history.json`。

### 工具与操作系统的边界

- 9 个文件工具（除 `remove_directory` 外）均通过 `os` / `os.path` 完成路径规范化与读写，作用于**本地文件系统**；
- `remove_directory` 依赖 `shutil.rmtree` 实现递归删除；
- `getDate` 通过 `subprocess` 调用 Windows `cmd` 的 `date /t`、`time /t`。

这条边界正是项目的设计要点：**大模型只做决策，本地代码负责执行**。
