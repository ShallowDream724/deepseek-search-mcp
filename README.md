# deepseek-search-mcp

将 DeepSeek 官方 Search / Fetch API 接入 MCP 客户端。提供 `search` 和 `fetch` 两个工具，支持 stdio 与 Streamable HTTP，保留旧客户端的 SSE 接入。

项目基于 [eggylan/deepseek-search-mcp](https://github.com/eggylan/deepseek-search-mcp)，使用 Python ≥ 3.10、FastMCP 4 和 httpx。调用搜索接口不需要指定语言模型，也不会额外调用模型生成答案。

## 安装

在项目目录中创建环境并安装：

```bash
python -m venv .venv
# Linux/macOS
.venv/bin/python -m pip install -e .
# Windows
.venv/Scripts/python.exe -m pip install -e .
```

下文的 `python` 应使用安装本项目的环境。密钥通过服务器环境变量 `DEEPSEEK_API_KEY` 或 HTTP 请求头传入，不放入工具参数和项目配置文件。

## 启动

```bash
# stdio：由 MCP 客户端启动进程
python -m deepseek_search_mcp

# Streamable HTTP：http://127.0.0.1:8000/mcp
python -m deepseek_search_mcp --transport http --port 8000

# SSE：兼容旧客户端
python -m deepseek_search_mcp --transport sse --port 8000
```

`streamable-http` 是 `http` 的别名；一次进程使用一种传输。HTTP 默认监听 `127.0.0.1`，可用 `--host`、`--port` 和 `--path` 修改。SSE 不使用 `--path`，入口为 `/sse`。日志只写 stderr；stdio 的 stdout 用于 MCP 协议。

## 接入 Codex

在 `~/.codex/config.toml` 中添加下面的配置，将路径换成自己的项目位置。Codex 桌面应用与 CLI 共用此文件。

```toml
[mcp_servers.deepseek-search]
command = "/absolute/path/deepseek-search-mcp/.venv/bin/python"
args = ["-m", "deepseek_search_mcp"]
cwd = "/absolute/path/deepseek-search-mcp"
env_vars = ["DEEPSEEK_API_KEY"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

Windows 使用 `.venv/Scripts/python.exe`。如果密钥保存为 Windows 用户级环境变量，而已运行的 Codex 尚未继承它，可使用本项目的启动脚本：

```toml
[mcp_servers.deepseek-search]
command = "C:/path/deepseek-search-mcp/.venv/Scripts/python.exe"
args = ["C:/path/deepseek-search-mcp/scripts/run-local.py"]
cwd = "C:/path/deepseek-search-mcp"
env_vars = ["DEEPSEEK_API_KEY"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

脚本优先使用进程环境变量；缺失时只读取 Windows 用户环境中的 `DEEPSEEK_API_KEY`，临时注入当前服务器进程。它不打印或写入密钥。修改配置后重新连接 MCP 或新开会话。配置方式见 [Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)。

HTTP 客户端示例：

```json
{
  "mcpServers": {
    "deepseek-search": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer <your-key>" }
    }
  }
}
```

请求头优先级为 `Authorization: Bearer …`、`X-DeepSeek-API-Key`，之后才使用服务器环境变量。因此，设置了服务器环境密钥的 HTTP 实例会为未传入密钥的请求使用该密钥。SSE 客户端须在发送工具调用的 POST 请求上也带请求头。

## 工具与参数

工具名称默认为 `search`、`fetch`。描述只说明用途、输入和返回内容；不要求模型固定采用某种写作风格或把结果评分当成事实依据。

### `search`

搜索网页，返回按上游顺序排列的来源、摘要和元数据。

| 参数 | 类型 | 说明 |
|---|---|---|
| `query` | string，必填 | 1–128 个字符，不能全为空白 |
| `count` | integer 或 null | 最多返回多少条，1–50；省略或 null 使用配置值，默认 10 |
| `ori_question` | string 或 null | 原始问题，供搜索引擎理解查询意图；提供时为 1–128 个字符且不能全为空白 |
| `need_content` | boolean | 默认 false；true 时附带可用正文，可能明显增大响应 |

`query` 支持 `site:`、`-site:`、`-keyword`、`"exact phrase"`、`-"excluded phrase"`、`lang:zh,en`、`after:`、`before:`。日期接受年份或 `YYYY-MM-DD`；多个站点用 OR 连接。示例：

```json
{"query":"DeepSeek site:github.com OR site:huggingface.co after:2026","count":5}
```

成功返回示例：

```json
{
  "ok": true,
  "query": "example",
  "count": 1,
  "results": [{
    "rank": 1,
    "rerank_score": 2.4,
    "title": "Example article",
    "url": "https://example.com/article",
    "snippet": "Short excerpt.",
    "summary": "Page summary.",
    "site_name": "Example",
    "site_icon": null,
    "date": null,
    "authority": 3,
    "content": null,
    "truncated": false
  }]
}
```

保留官方的 `rerank_score`、`site_name`、`site_icon` 等字段名，增加从 1 开始的 `rank` 和正文截断标志 `truncated`。`count` 是实际返回条数。`rerank_score` 是上游相关性评分（0–3），`authority` 是上游来源评级（0–4，-1 表示未知）。站点名称、图标与日期可能为 null。`content` 未请求或不可用时为 null；可用时按配置截断。

空结果是正常成功：`{"ok":true,"query":"…","count":0,"results":[]}`。结构损坏的结果会返回 `invalid_response`，不会静默丢弃后冒充空结果。

### `fetch`

读取指定网页，返回标题和 Markdown 正文。

| 参数 | 类型 | 说明 |
|---|---|---|
| `url` | string，必填 | 最长 8192 字符的 HTTP(S) 绝对地址，须含主机名，不能含用户名、密码、空格或控制字符 |
| `max_chars` | integer 或 null | 返回正文字符上限；省略或 null 使用配置值，默认 30000；0 返回完整正文 |

```json
{
  "ok": true,
  "url": "https://example.com/article",
  "title": "Example article",
  "content": "# Example article\n\nArticle content.",
  "truncated": false,
  "total_chars": 35
}
```

`total_chars` 是截断前的正文长度。`truncated=true` 时，可增大 `max_chars` 或设为 0 重新读取。上游用 `title: ""` 表示无标题；标题字段缺失或类型错误、缺少正文、正文类型错误或空白正文均视为异常响应。

## MCP 返回与错误

两个工具均声明 `inputSchema` 与成功响应的 `outputSchema`。成功内容同时返回 JSON 文本和 `structuredContent`；参数、鉴权、上游或网络错误均设置 MCP `isError: true`。预期错误也同时提供 JSON 文本和以下结构化内容：

```json
{
  "ok": false,
  "error": {
    "status": "rate_limited",
    "http_code": 429,
    "message": "The service returned HTTP 429. …",
    "retryable": true,
    "retry_after_seconds": 30
  }
}
```

`http_code` 在无上游 HTTP 状态时为 null。`retry_after_seconds` 只在上游返回有效 `Retry-After` 时出现。`retryable` 表示相同请求稍后可能成功。错误结果不要求匹配成功响应的 `outputSchema`；未知工具、协议错误及意外内部异常由 MCP 框架处理，内部异常详情对客户端隐藏。

| status | 原因 | 可重试 |
|---|---|---|
| `missing_api_key` | 无可用密钥 | 否 |
| `invalid_request` | 参数校验失败或上游 400 | 否 |
| `unauthorized` | 401，密钥无效 | 否 |
| `insufficient_balance` | 402，余额不足 | 否 |
| `forbidden` | 403，抓取被策略拒绝 | 否 |
| `not_found` | 404，无可用页面内容 | 否 |
| `upstream_timeout` | 408、504 或请求超时 | 是 |
| `payload_too_large` | 413，请求过大 | 否 |
| `rate_limited` | 429，限流 | 是 |
| `server_error` | 其他 5xx | 是 |
| `network_error` | 连接或传输错误 | 是 |
| `invalid_response` | 200 响应不是合法 JSON，或内容结构不符合契约 | 否 |

仅重试 408、429、5xx 和网络错误，默认最多重试 2 次。退避从 0.5 秒开始翻倍；有效 `Retry-After` 优先。若要求等待超过 10 秒，直接返回错误及等待时长，避免过早重试。取消调用会停止请求和后续重试。网络超时可能发生在服务端已经处理请求之后，不承诺重试绝无额外计费。

参数类型严格校验：例如 `need_content: "false"`、`count: true`、`max_chars: 1.5` 都会报错。密钥不作为参数暴露；上游错误中的当前密钥、`sk-…` 和 Bearer token 会被脱敏。参数校验错误不会回显输入值。

## 服务器配置

配置查找顺序：`--config` → `DEEPSEEK_SEARCH_CONFIG` → 工作目录的 `config.json` → 内置默认值。显式指定但不存在的路径、无效 JSON、未知配置字段均使启动失败（退出码 2）。更改配置后需重启服务器。

复制 `config.example.json` 后按需修改：

```json
{
  "tools": {
    "search": { "name": "search", "enabled": true },
    "fetch": { "name": "fetch", "enabled": true }
  },
  "api": {
    "base_url": "https://api.deepseek.com",
    "timeout_seconds": 30,
    "max_retries": 2
  },
  "search": {
    "default_count": 10,
    "max_content_chars": 20000,
    "localization": ""
  },
  "fetch": { "max_content_chars": 30000 }
}
```

工具可单独改名或禁用，名称为 1–64 位字母、数字、下划线或连字符；启用的工具不能重名。`api.base_url` 可含网关路径前缀，不接受凭据、查询串或 fragment。`timeout_seconds` 是单次 HTTP 操作超时，大于 0 且不超过 300；`max_retries` 为 0–5。增加它们后，应相应提高客户端的工具超时。

`search.localization` 为 IPv4/IPv6 地址或空字符串，只用于部署配置，不交给模型猜测。两个 `max_content_chars` 均为非负整数，0 不截断。

旧版迁移：默认名称由 `web_search` / `web_fetch` 改为 `search` / `fetch`，可通过上述配置恢复旧名；结果中的 `score`、`site` 改回官方 `rerank_score`、`site_name`；调用失败现在会设置 `isError=true`。解析旧格式的客户端需要同步调整。

## 验证

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
# 真实 API 测试；需要 DEEPSEEK_API_KEY，会产生少量请求费用
python -m pytest -m live -v
```

默认测试不访问公网，覆盖输入校验、响应映射、错误码、重试、密钥脱敏，以及真实子进程 stdio / Streamable HTTP 的工具发现与调用。HTTP 测试使用本机模拟上游，也验证逐请求传入密钥。live 测试仅从环境读取密钥，不读取密钥文件。

## 官方接口与计费

- [Search / Fetch 指南](https://api-docs.deepseek.com/guides/search/)
- [Search 参数与响应](https://api-docs.deepseek.com/api/search/)
- [Fetch 参数与响应](https://api-docs.deepseek.com/api/fetch/)

截至 2026-10-17，英文文档列价为 Search、Fetch 各 **US$0.75 / 1000 次成功请求**；搜索结果条数不改变单价。空搜索结果、失败与超时按官方说明不计费。Search、Fetch 各自按账号限流 5 QPS，多个密钥共享额度；Fetch 另有站点限流。实际价格及计费规则以官方最新文档为准。

## 许可证

MIT，保留上游 LICENSE。
