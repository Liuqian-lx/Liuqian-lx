# AnythingLLMWebpage（知识库前端网页）

AnythingLLM 的本地前端工作台：上传本地文档、管理/切换工作区、上传后查看
文档树，配合 `AnythingLLMMCP` 提供的 `workspace_search` / `workspace_chat`
工具使用。

## 启动

双击 `serve.bat`，或在 PowerShell 中执行：

```powershell
cd D:\Liuqian-lx\AnythingLLMWebpage
python -m http.server 8092 --bind 127.0.0.1
```

然后浏览器访问 <http://127.0.0.1:8092/index.html>（`serve.bat` 会自动打开）。

> 必须通过 HTTP 访问，不要直接双击 `index.html`：`file://` 协议下浏览器
> 会按 `null` 来源处理请求，AnythingLLM 的 API 可能被 CORS 拦截。

## 配置

页面顶部填写：

- **API 地址**：默认 `http://localhost:3001/api`（AnythingLLM 本体地址）；
- **API Key**：在 AnythingLLM → Settings → Developer API Key 中生成。

点击「保存并连接」后，地址与密钥只保存在浏览器 `localStorage`，
**不会写入仓库文件**；`index.html` 中不包含任何硬编码密钥。

## 前置条件

AnythingLLM 本体需已启动（默认监听 `http://127.0.0.1:3001`）。
