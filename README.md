# deepseek-search-mcp

把 DeepSeek 的 **网页搜索（Search）** 和 **网页抓取（Fetch）** 包装成 MCP 工具，供 Claude Desktop、Cursor、VS Code、Cline 等任意 MCP 客户端调用。

- 基于 [FastMCP 4](https://gofastmcp.com) 构建，Python ≥ 3.10
- 同时支持 **stdio**、**Streamable HTTP**、**SSE** 三种传输
- DeepSeek API Key 由**客户端逐请求传入**，服务器原样转发，不存储、不落盘、不写日志
- 工具名可在 `config.json` 中自定义，避免与其他 MCP 服务器的工具重名
- 所有返回都是结构化 JSON：成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": {...}}`

DeepSeek 接口契约以官方文档为准：<https://api-docs.deepseek.com/zh-cn/guides/search>

---

## 1. 安装

推荐直接装进现有 conda 环境（例如 `mcp-dev`）：

```bash
conda activate mcp-dev
cd F:/Dev/deepseek-search-mcp
pip install -e .
```

安装完成后会得到两个等价入口：

```bash
deepseek-search-mcp --help
python -m deepseek_search_mcp --help
```

依赖：`fastmcp>=4.1,<5`、`httpx>=0.28`。

---

## 2. 启动与传输

| 传输 | 启动命令 | 端点 |
|---|---|---|
| stdio（默认） | `deepseek-search-mcp` | 标准输入输出 |
| Streamable HTTP | `deepseek-search-mcp --transport http --port 8000` | `http://127.0.0.1:8000/mcp` |
| SSE（兼容旧客户端） | `deepseek-search-mcp --transport sse --port 8000` | `http://127.0.0.1:8000/sse` |

`--transport streamable-http` 是 `http` 的同义词。一次进程只服务一种传输。

常用参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--transport` | `stdio` | `stdio` / `http` / `streamable-http` / `sse` |
| `--host` | `127.0.0.1` | HTTP/SSE 监听地址，对外提供服务用 `0.0.0.0` |
| `--port` | `8000` | HTTP/SSE 监听端口 |
| `--path` | `/mcp` | Streamable HTTP 端点路径（SSE 不适用） |
| `--config` | 见第 3 节 | 配置文件路径 |
| `--log-level` | `INFO` | 日志级别，只写 stderr |

> stdio 模式下 stdout 是 MCP 协议通道，本项目的所有提示和日志都只写 stderr，不会污染协议。

---

## 3. 配置

### 3.1 查找顺序

从高到低：

1. `--config /path/to/config.json`
2. 环境变量 `DEEPSEEK_SEARCH_CONFIG`
3. 当前工作目录下的 `./config.json`
4. 代码内置默认值（无需任何文件即可启动）

- 只缺 `./config.json` 不算错误：直接用默认值，适合 stdio 零配置启动。
- 显式指定的路径不存在、JSON 语法错误、字段类型/取值非法：**启动即失败，退出码 2**。
- 未知字段会报错（防拼写错误），不会静默忽略。

启动时 stderr 会打一行来源说明：

```
[config] loaded ./config.json (tools: web_search, web_fetch)
```

### 3.2 示例

复制 `config.example.json` 为 `config.json` 后修改（`config.json` 已被 `.gitignore` 忽略）：

```json
{
  "tools": {
    "search": { "name": "web_search", "enabled": true },
    "fetch":  { "name": "web_fetch",  "enabled": true }
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
  "fetch": {
    "max_content_chars": 30000
  }
}
```

### 3.3 字段说明

| 字段 | 默认值 | 说明 |
|---|---|---|
| `tools.search.name` | `web_search` | 搜索工具的 MCP 名称，`[A-Za-z0-9_-]`，1–64 字符 |
| `tools.search.enabled` | `true` | 为 `false` 时完全不注册该工具 |
| `tools.fetch.name` | `web_fetch` | 抓取工具的 MCP 名称；两个工具名不可相同 |
| `tools.fetch.enabled` | `true` | 同上 |
| `api.base_url` | `https://api.deepseek.com` | 可指向代理/网关；允许带路径前缀，如 `https://gw.example.com/deepseek` |
| `api.timeout_seconds` | `30` | 单次 HTTP 请求超时（1–300） |
| `api.max_retries` | `2` | 瞬时错误的最大重试次数（0–5） |
| `search.default_count` | `10` | `count` 未传时的默认条数（1–50） |
| `search.max_content_chars` | `20000` | 搜索返回正文的截断长度，`0` 表示不截断 |
| `search.localization` | `""` | 用于本地化结果的出口 IP（IPv4/IPv6），空表示不传；**不暴露给模型** |
| `fetch.max_content_chars` | `30000` | 抓取正文的默认截断长度，`0` 表示不截断 |

改配置需要重启服务器。

---

## 4. 鉴权：Key 怎么传

服务器**不保存密钥**，每次工具调用都重新解析，并原样作为 `Authorization: Bearer <key>` 转发给 DeepSeek。解析顺序：

1. HTTP 请求头 `Authorization: Bearer <key>`（HTTP / SSE 传输）
2. HTTP 请求头 `X-DeepSeek-API-Key: <key>`（无法设置 Authorization 的客户端）
3. 环境变量 `DEEPSEEK_API_KEY`（stdio 传输，或给 HTTP 服务器做兜底）

都没有时不会抛异常，而是返回：

```json
{
  "ok": false,
  "error": {
    "status": "missing_api_key",
    "http_code": null,
    "message": "No API key provided. On HTTP transports send 'Authorization: Bearer <key>' with the request; when running over stdio, set the server's API key environment variable.",
    "retryable": false
  }
}
```

安全约定：

- 密钥只存在于请求头字典中，不写入磁盘、不缓存、不进入日志。
- 错误信息经过脱敏，`sk-...` 与 `Bearer ...` 会变成 `sk-***` / `Bearer ***`。
- `.temp/`、`config.json` 已在 `.gitignore` 中。

---

## 5. 工具

> 工具名、标题、描述、参数说明与服务器 instructions 均为中性表述，不含上游厂商名称——agent 看到的只是一个普通的网页搜索 / 抓取工具。上游厂商仅在错误诊断信息和本文档中出现。

### 5.1 `web_search`（名称可改）

```python
web_search(
    query: str,                    # 必填，1–128 字符，不能全空白
    count: int | None = None,      # 1–50，缺省用 search.default_count
    ori_question: str | None = None,  # 用户原始问题，帮助理解搜索意图，≤128 字符
    need_content: bool = False     # true 时返回网页正文（响应会大很多）
) -> dict
```

成功返回：

```json
{
  "ok": true,
  "query": "DeepSeek V4 发布",
  "count": 2,
  "results": [
    {
      "rank": 1,
      "score": 2.4,
      "title": "DeepSeek V4 模型发布",
      "url": "https://example.com/deepseek-v4",
      "snippet": "DeepSeek V4 已上线，支持工具调用与长上下文。",
      "summary": "DeepSeek 发布了 V4 模型。此次发布改进了工具调用与长上下文能力……",
      "site": "Example News",
      "date": "2026-06-01T00:00:00+00:00",
      "authority": 3,
      "content": null,
      "truncated": false
    }
  ]
}
```

字段映射：`rerank_score → score`、`site_name → site`，新增 `rank`（从 1 开始）与 `truncated`，丢弃对模型无用的 `site_icon`。`score ∈ [0, 3]`，`≥ 1.5` 为优质结果；`authority ∈ [0, 4]`（`-1` 未知），`≥ 3` 为极权威。`content` 仅在 `need_content=true` 时有值，超过 `search.max_content_chars` 会截断并置 `truncated: true`。

#### 搜索语法（原样透传给 DeepSeek）

| 操作符 | 示例 | 作用 |
|---|---|---|
| `site:` | `DeepSeek site:github.com` | 限定站点；多个用空格 + OR：`site:github.com OR site:huggingface.co` |
| `-site:` | `DeepSeek -site:example.com` | 排除站点 |
| `-` | `DeepSeek -广告` | 排除含关键词的页面 |
| `"..."` | `DeepSeek "精确短语"` | 精确短语匹配 |
| `-"..."` | `DeepSeek -"release notes"` | 排除精确短语 |
| `lang:` | `DeepSeek lang:zh,en` | 限定语言，逗号分隔 |
| `after:` / `before:` | `DeepSeek after:2025` | 限定发布时间，支持 `2025` 或 `2025-01-01` |

示例：`DeepSeek 模型 site:github.com OR site:huggingface.co lang:zh after:2025`

### 5.2 `web_fetch`（名称可改）

```python
web_fetch(
    url: str,                  # 必填，http/https，≤8192 字符，不能带用户名密码
    max_chars: int | None = None  # 正文字符上限，缺省用 fetch.max_content_chars
) -> dict
```

成功返回：

```json
{
  "ok": true,
  "url": "https://example.com/article",
  "title": "Example article",
  "content": "# Example article\n\nArticle content.",
  "truncated": false
}
```

抓取结果受目标站点的可用性与访问策略影响：站点拒绝、无正文、类型不支持等会返回 `not_found`。

---

## 6. 返回与错误

所有失败都是**结构化对象**，不会把 MCP 工具调用标记为异常：

```json
{
  "ok": false,
  "error": {
    "status": "rate_limited",
    "http_code": 429,
    "message": "… The service limits Search and Fetch to 5 QPS per account; wait a moment and retry.",
    "retryable": true
  }
}
```

`message` 会保留 DeepSeek 原文并追加可操作提示。`retryable: true` 表示同样的调用稍后重试可能成功。

| `status` | 触发条件 | `retryable` |
|---|---|---|
| `missing_api_key` | 请求头与环境变量都没有 Key | false |
| `invalid_request` | 本地参数校验失败，或上游 400 | false |
| `unauthorized` | 401，Key 缺失/无效 | false |
| `insufficient_balance` | 402，账号余额不足 | false |
| `forbidden` | 403，Fetch 被安全策略拒绝 | false |
| `not_found` | 404，抓不到可用网页正文 | false |
| `upstream_timeout` | 408，或本地连接/读取超时 | true |
| `payload_too_large` | 413 | false |
| `rate_limited` | 429，超过 QPS | true |
| `server_error` | 5xx | true |
| `network_error` | DNS/连接失败等传输层错误 | true |
| `invalid_response` | 上游 200 但 JSON 非法或结构异常 | false |

**重试策略**：仅对 `408/429/5xx` 和网络错误重试，最多 `api.max_retries` 次，指数退避 `0.5s → 1s …`，若响应带 `Retry-After` 则优先采用，单次等待封顶 10 秒。

---

## 7. 客户端配置示例

### 7.1 Claude Desktop（stdio）

`claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "deepseek-search": {
      "command": "deepseek-search-mcp",
      "args": [],
      "env": { "DEEPSEEK_API_KEY": "sk-你的密钥" }
    }
  }
}
```

如果 `deepseek-search-mcp` 不在 PATH 上，把 `command` 换成绝对路径，例如
`H:\\AnaConda\\envs\\mcp-dev\\Scripts\\deepseek-search-mcp.exe`。

### 7.2 Cursor / VS Code（Streamable HTTP）

先启动服务器：

```bash
deepseek-search-mcp --transport http --host 127.0.0.1 --port 8000
```

客户端 `mcp.json`：

```json
{
  "mcpServers": {
    "deepseek-search": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer sk-你的密钥" }
    }
  }
}
```

### 7.3 SSE（旧客户端兼容）

```bash
deepseek-search-mcp --transport sse --port 8000
```

```json
{
  "mcpServers": {
    "deepseek-search": {
      "url": "http://127.0.0.1:8000/sse",
      "headers": { "Authorization": "Bearer sk-你的密钥" }
    }
  }
}
```

> SSE 的工具调用走 `POST /messages/`，客户端必须在这条请求上也带 `Authorization`（主流客户端会把配置的头应用到所有请求）。若你的客户端只在首个 `GET /sse` 上带头，请改用 Streamable HTTP，或给服务器进程设置 `DEEPSEEK_API_KEY` 兜底。

### 7.4 改名避免工具冲突

同时接入多个搜索类 MCP 服务器时，在 `config.json` 里改名：

```json
{
  "tools": {
    "search": { "name": "deepseek_search", "enabled": true },
    "fetch":  { "name": "deepseek_fetch",  "enabled": true }
  }
}
```

重启后客户端看到的工具名即为 `deepseek_search` / `deepseek_fetch`。

---

## 8. 测试

```bash
# 全部单元测试：全 mock，无网络，秒级
pytest -q

# 真实调用 DeepSeek（需要 Key）
pytest -m live -v
```

真实测试的 Key 来源：优先 `DEEPSEEK_API_KEY`，否则读 `.temp/test-key.txt`（文件里任意位置匹配 `sk-...` 即可，`.temp/` 已被忽略）。

当前覆盖：配置发现与校验、参数构造、结果映射与截断、重试与退避、全部错误码映射、密钥脱敏、工具注册/改名/禁用、三种传输的真实端到端。

---

## 9. 计费与限速

- Search、Fetch 均按**请求次数**计费：每 1000 次成功请求 5 元；`count` 不影响单价。
- 只有 HTTP 200 且产生结果的请求才计费；失败、无结果、超时不计费，因此本项目对 `429/5xx` 的自动重试不会额外花钱。
- 每个账号 Search 与 Fetch **各自** 5 QPS，与使用哪个 Key 无关；超过返回 429。
- 遇到 402 请先充值；其它 4xx 在未修改请求前不要重试（本项目已按此处理）。

---

## 10. 项目结构

```
src/deepseek_search_mcp/
├─ config.py     配置加载、查找顺序、Pydantic 校验
├─ models.py     返回信封与错误对象的 TypedDict 定义
├─ auth.py       Key 解析（请求头 → 别名头 → 环境变量）与脱敏
├─ client.py     httpx 客户端、重试退避、错误映射、结果映射与截断
├─ server.py     FastMCP 服务器与两个工具的注册（动态工具名）
└─ cli.py        命令行参数 → mcp.run(transport=...)
tests/           133 个单元测试 + 4 个 live 测试
config.example.json
```

---

## 11. 已知限制

- SSE 是 MCP 的旧传输，FastMCP 把它定位为兼容模式；新项目请用 Streamable HTTP。
- 一次进程只服务一种传输（stdio / http / sse 三选一）。
- 修改 `config.json` 后需要重启进程。
- Windows 控制台若出现中文乱码，是终端代码页问题（`chcp 65001`），不影响 MCP 协议中的 UTF-8 内容。

---

## 12. 许可证

MIT
