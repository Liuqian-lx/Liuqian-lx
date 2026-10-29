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
│   ├── session.py          # 上下文维护、工具闭环、历史读写
│   └── tools/
│       ├── __init__.py     # TOOLS / TOOL_MAP 汇总、execute_tool
│       ├── builtin.py      # 内置工具
│       ├── file_ops.py     # 文件操作工具
│       ├── web_search.py   # 联网搜索工具 searchWeb
│       └── web_fetch.py    # 网页正文提取工具 fetchWebPage
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

## 验证

```bash
python verify_core.py
```

脚本不导入 `tui`、不发起真实网络请求，覆盖：配置读取、14 个工具注册与重名检查、
内置/文件工具、流式回调、工具闭环、历史加载/保存，以及 `searchWeb` 的
未配置 Key、空 query、网络异常、HTTP 错误、非法 JSON、结果归一化与空结果，
和 `fetchWebPage` 的空/非法 URL、curl 缺失/超时、网络失败、HTTP 4xx、
解析异常、空正文、8000 字符截断与 trafilatura 正文提取。

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
