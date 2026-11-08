---
name: office-document-generator
description: 调用本地 OfficeCli 命令行工具，快速生成和编辑 Word、Excel、PPT 文档
---

# Office 文档生成（OfficeCli）

## 技能概述

本 Skill 通过项目内置的 `RunCli` 工具调用本地 OfficeCli 命令行程序，无需安装
Microsoft Office，即可创建、编辑和检查 `.docx`、`.xlsx`、`.pptx` 文档。

- **主程序**：`D:\Dwonload\OfficeCli\OfficeCli_#SULP#_26sc1d\officecli-win-x64.exe`
- **版本**：1.0.158（`--version` 实测）
- **形态**：单文件可执行程序，无第三方依赖，无需 Office 环境
- **工作层次**：优先 L1 读取 → L2 DOM 编辑 → L3 raw XML；不确定属性名或语法时，
  先执行 `help`，不要猜
- **结构化输出**：所有命令都支持 `--json`

## 支持的文档类型与能力

| 类型 | 扩展名 | 主要能力 |
| --- | --- | --- |
| Word | `.docx` | 段落/标题、run、表格、图片、页眉页脚、批注、目录、域、样式、书签、分页、文本框 |
| PowerPoint | `.pptx` | 新建幻灯片、形状/文本框、图片、表格、图表、连接线、组合、音视频、动画、切换、备注、母版/版式 |
| Excel | `.xlsx` | 工作表、行列单元格、公式、图表、数据透视表、条件格式、迷你图、数据验证、筛选、命名区域 |

读取与检查能力：

- `view <file> <mode>`：`outline`（结构）、`stats`（统计）、`issues`（问题）、
  `text`（纯文本）、`annotated`、`html`
- `get <file> <path>`、`query <file> <selector>`：按路径或 CSS 风格选择器读取
- `validate <file>`：按 OpenXML Schema 校验

> 内置格式只有 `docx`、`xlsx`、`pptx`。`.doc`、`.hwpx`、PDF 导出、截图等能力
> 依赖额外插件或运行环境，使用前先用 `help` / `plugins list` 确认；不确定时不要承诺。

## 调用方式（通过 RunCli）

`RunCli` 的 `command` 传主程序绝对路径，`args` 传参数数组。命令不经过 shell，
数组中的每个元素都是一个完整参数。

```json
{
  "command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
  "args": ["create", "D:/output/report.docx", "--json"]
}
```

要点：

- 不要把整条命令拼成一个字符串，也不要给参数加 shell 引号；
  `text=Executive Summary` 应原样作为一个数组元素传入。
- 路径推荐使用绝对路径；Windows 下正斜杠 `/` 同样可用（已实测），
  还能避免 JSON 中的反斜杠转义。工具路径中的 `#` 经 RunCli 传递是安全的。
- **必须检查退出码**：RunCli 只要进程成功启动就返回 `success: true`，
  即使 OfficeCli 以非 0 退出码失败。请读取 `result.exit_code`
  （0 = 成功，1 = 失败，2 = 有警告）和 `result.stderr`。
- 生成完成后执行 `close <file>`，把内存中的改动落盘并释放文件。

命令结构：

```text
officecli-win-x64.exe <命令> [文件] [路径] [--type 类型] [--prop key=value ...] [--json]
```

## 核心参数说明

### 常用命令

| 命令 | 作用 | 关键参数 |
| --- | --- | --- |
| `create <file>` | 新建空白文档，类型由扩展名决定 | `--type`、`--force`、`--locale zh-CN`、`--minimal` |
| `add <file> <parent>` | 添加元素 | `--type`、`--prop k=v`、`--after/--before`、`--index`、`--from` |
| `set <file> <path>` | 修改元素属性 | `--prop k=v`、`--find`、`--replace` |
| `get <file> <path>` | 读取节点 | `--depth N`、`--json` |
| `query <file> <selector>` | CSS 风格查询 | `[attr=value]`、`:contains("text")` |
| `view <file> <mode>` | 预览/检查 | `text`、`outline`、`stats`、`issues` |
| `validate <file>` | Schema 校验 | — |
| `open / save / close <file>` | 常驻模式管理 | — |
| `batch <file>` | 一次执行多条命令 | `--commands`、`--input`、`--best-effort` |
| `raw / raw-set` | 直接操作 XML | `--xpath`、`--action`、`--xml` |

### 路径与属性规则

- docx 正文父路径是 `/body`；pptx 幻灯片挂在 `/`，幻灯片内的形状在 `/slide[N]`；
  xlsx 使用 `/Sheet1/A1` 这类路径。
- DOM 路径索引从 **1** 开始：`/body/p[1]`、`/slide[1]`；`--index` 从 **0** 开始
  （xlsx 的 `add --type row/col` 例外，从 1 开始）。
- 所有属性统一写成 `--prop key=value`，没有 `--name` 之类的独立参数。
- 常见值格式：长度 `2cm`、`2.54cm`、`1in`、`72pt`；颜色 `FF0000`、`#FF0000`、
  `red`、`accent1`；文本换行在 `--prop text=...` 中用 `\n`。
- 含方括号的路径（如 `/slide[1]`）通过 RunCli 数组参数直接传字面值即可；
  若在 shell 中手写命令，需要用引号包住。

## 完整使用示例

### 示例 1：生成 Word 文档

按顺序调用 RunCli（每一步都是独立的工具调用）：

1. 新建文档

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["create", "D:/output/report.docx", "--json"]}
```

2. 添加标题段落

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["add", "D:/output/report.docx", "/body", "--type", "paragraph",
          "--prop", "text=2025年第四季度经营报告", "--prop", "style=Heading1"]}
```

3. 添加正文段落

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["add", "D:/output/report.docx", "/body", "--type", "paragraph",
          "--prop", "text=营收同比增长25%。"]}
```

4. 检查并落盘

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["view", "D:/output/report.docx", "text"]}
```

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["close", "D:/output/report.docx"]}
```

预期 `view text` 输出两行段落文本；`close` 返回 `Resident closed for report.docx`。

### 示例 2：生成 PowerPoint 演示文稿

1. 新建演示文稿并添加一页幻灯片（标题 + 背景色）

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["create", "D:/output/deck.pptx", "--json"]}
```

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["add", "D:/output/deck.pptx", "/", "--type", "slide",
          "--prop", "title=Q4 Report", "--prop", "background=1A1A2E"]}
```

2. 在幻灯片上添加形状/文本框

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["add", "D:/output/deck.pptx", "/slide[1]", "--type", "shape",
          "--prop", "text=Revenue grew 25%", "--prop", "x=2cm", "--prop", "y=5cm",
          "--prop", "font=Arial", "--prop", "size=24", "--prop", "color=FFFFFF"]}
```

3. 检查并落盘

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["view", "D:/output/deck.pptx", "text"]}
```

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["close", "D:/output/deck.pptx"]}
```

预期 `view text` 输出 `=== /slide[1] ===`、标题与形状文本。

### 示例 3：生成 Excel 工作簿

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["create", "D:/output/data.xlsx", "--json"]}
```

```json
{"command": "D:\\Dwonload\\OfficeCli\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe",
 "args": ["set", "D:/output/data.xlsx", "/Sheet1/A1",
          "--prop", "value=Name", "--prop", "bold=true"]}
```

## 注意事项

1. **输出路径**
   - `create` 写入参数指定的路径，扩展名决定文档类型；不会自动创建父目录，
     父目录不存在会返回 `Could not find a part of the path`。
     可先用 `create_directory` 工具建好目录。
   - 相对路径相对于 Agent 进程的工作目录（Agent_L），建议始终使用绝对路径。
   - 目标文件已存在时默认拒绝覆盖；确需覆盖用 `--force`。
2. **中文与特殊字符**
   - 已实测支持中文文件名和中文正文；请保证调用方以 UTF-8 传递文本。
   - 工具路径包含 `#`，经 RunCli 的数组参数传递无需转义；若在 shell 中手写，
     需要用引号包住路径。
3. **常驻进程与文件锁**
   - 每条命令会自动启动常驻进程以加速后续操作。若提示
     `currently opened by a resident process`，先执行 `close <file>` 再重试。
   - 其他程序（Word/WPS、python-docx、上传/预览）读取文件前，先执行
     `save <file>`（保留常驻）或 `close <file>`（落盘并释放）。
4. **RunCli 限制**
   - 单条命令超时 30 秒；复杂任务拆分为多条命令，或用 `batch` 合并。
   - stdout/stderr 各截断到 4000 字符；需要精确结果时加 `--json`。
   - 必须根据 `exit_code` 判断成败，不能只看 `success`。
5. **常见问题**
   - `Unsupported file type`：扩展名不是 `.docx/.xlsx/.pptx`。
   - `style 'Heading1' was not defined` 是警告，工具会自动补上内置样式，可忽略。
   - PPT 的 `shape[1]` 通常是标题占位符，正文形状用 `shape[2]` 或稳定 `@id=` 路径。
   - 修改完成后用 `validate` 或 `view issues` 复查。
   - 属性名不确定时执行 `help <格式> <元素>`，例如
     `help docx paragraph`、`help pptx shape`、`help xlsx cell`。
