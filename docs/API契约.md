# 前端 API 契约（cc-wire-analyzer）

> 给 Fable 接手前端设计时的后端接口契约。后端按此实现，前端按此调用。变更需双方同步。

所有 UI 路由前缀 `/api/`（代理 catch-all 不碰这个前缀）。返回 JSON，UTF-8。

---

## 1. 代理控制

### `POST /api/proxy/start` — 启动代理

启动本地代理 server + 备份 settings.json + 改写 BASE_URL 指向本地。

**请求**：无 body（或 `{}`）

**响应** `200`：
```json
{
  "running": true,
  "listen": "http://127.0.0.1:5051",
  "upstream": "https://api.anthropic.com",
  "backup_created": "~/.cc-wire-analyzer/backups/settings.json.20260705-224300",
  "orphan_recovered": null
}
```

**响应** `409`（已在运行）：
```json
{ "running": true, "listen": "...", "error": "already_running" }
```

**响应** `500`（启动失败，settings.json 未被改）：
```json
{ "running": false, "error": "port_unavailable|write_failed|...", "detail": "..." }
```

### `POST /api/proxy/stop` — 停止代理

停 server + 恢复 settings.json BASE_URL。

**响应** `200`：
```json
{ "running": false, "restored_to": "https://api.anthropic.com" }
```

### `GET /api/proxy/status` — 当前状态

```json
{
  "running": true,
  "listen": "http://127.0.0.1:5051",
  "upstream": "https://api.anthropic.com",
  "original_base_url": "https://api.anthropic.com",
  "started_at": "2026-07-05T22:43:00",
  "backups_count": 3,
  "orphan_recovered_at_startup": null
}
```

`orphan_recovered_at_startup`：若非 null，说明上次崩溃未恢复、本次启动已自动恢复，UI 应弹提示。

---

## 2. 捕获列表

### `GET /api/captures?date=YYYY-MM-DD&limit=200&offset=0` — 列表

**查询参数**：
- `date`（可选，默认今天）：捕获日期，对应文件 `captures/<date>.jsonl`
- `limit`（默认 200，最大 1000）
- `offset`（默认 0，分页）

**响应**：
```json
{
  "date": "2026-07-05",
  "total": 42,
  "items": [
    {
      "id": "req_a1b2c3d",
      "ts_start": "2026-07-05T22:43:12.345",
      "method": "POST",
      "path": "/v1/messages",
      "model": "glm-5.2",
      "status": 200,
      "ttft_ms": 340,
      "total_ms": 4521,
      "usage": { "input": 12340, "output": 567, "cache_read": 8000, "cache_creation": 0 },
      "stop_reason": "end_turn",
      "has_error": false,
      "summary": "用户问：帮我写一个..."   // 前 80 字摘要（assistant 首条 text）
    }
  ],
  "dates_available": ["2026-07-05", "2026-07-04"]
}
```

### `GET /api/captures/<id>` — 单请求详情

**响应** `200`：完整记录（见落盘结构）。
```json
{
  "id": "req_a1b2c3d",
  "ts_start": "...", "ts_end": "...",
  "method": "POST",
  "path": "/v1/messages",
  "upstream": "https://api.anthropic.com/v1/messages",
  "request": {
    "headers_safe": { "content-type": "...", "anthropic-version": "...", "authorization": "<redacted>", "user-agent": "..." },
    "body": {
      "model": "glm-5.2",
      "max_tokens": 32000,
      "system": [ {"type":"text","text":"...","cache_control":{"type":"ephemeral"}}, ... ],
      "tools": [ ... ],
      "messages": [ {"role":"user","content":[...]}, ... ],
      "metadata": { "user_id": "..." },
      "stream": true
    }
  },
  "response": {
    "status": 200,
    "headers_safe": { ... },
    "ttft_ms": 340,
    "total_ms": 4521,
    "stop_reason": "end_turn",
    "usage": { "input": 12340, "output": 567, "cache_read": 8000, "cache_creation": 0 },
    "content_blocks": [
      {"type":"thinking","text":"..."},
      {"type":"text","text":"..."},
      {"type":"tool_use","id":"toolu_xxx","name":"Read","input":{...}}
    ],
    "chunks_count": 42
  },
  "error": null
}
```

`error` 非 null 时：
```json
{ "error": { "kind": "upstream_5xx|upstream_4xx|connect|timeout|parse", "status": 502, "body_snippet": "..." } }
```

### `GET /api/captures/stream` — LIVE SSE 推送

新请求落盘时实时推送。`text/event-stream`。

```
event: capture
data: {"id":"req_...","ts_start":"...","path":"/v1/messages","model":"glm-5.2","status":200, ...}

event: capture
data: {...}

: ping
```

前端用 `EventSource` 订阅，收到 `capture` 事件防抖 300ms 后插入列表顶部。心跳 `: ping` 保活。

### `GET /api/dag?date=YYYY-MM-DD` — 时序 DAG（View D）

返回当日全量捕获经 `classifier.build_dag` 推断的结构：节点（按 kind 分类 + 会话线 lane）、三种边（seq 同 lane 相邻 / trigger 主线 Task prompt 匹配子代理 / near 辅助挂最近主线）。

```json
{
  "nodes": [{"id":"req_…","ts_start":"…","kind":"main|subagent|title|compact|security|count_tokens|other","lane":"s-<hash>|agent-<hash>|aux","model":"glm-5.2","status":200,"total_ms":4521,"usage":{...},"has_error":false,"summary":"…"}],
  "edges": [{"from":"req_…","to":"req_…","type":"seq|trigger|near"}],
  "lanes": [{"lane_id":"s-…","kind":"main|subagent|aux","first_ts":"…","count":3}]
}
```

### `POST /api/captures/clear` — 清除录制（260712）

**请求**：`{ "date": "2026-07-12", "mode": "purge"|"archive" }`。`date` 缺省=今天；`mode` 缺省=`purge`。`date` 经 `YYYY-MM-DD` 格式 + 语义校验（防路径穿越）。

- `mode=purge`：直接删 `captures/<date>.jsonl`
- `mode=archive`：先压缩到 `archives/<date>.<HHMMSS>.jsonl.zip`（ZIP_DEFLATED 优先，zlib 缺失降级 ZIP_STORED），再删原文件

**响应**：
```json
// purge
{ "ok": true, "removed": 42 }
// archive
{ "ok": true, "removed": 42, "archive": { "path": "~/.cc-wire-analyzer/archives/2026-07-12.193021.jsonl.zip", "size": 12345, "compressed": true } }
// 失败（HTTP 500）
{ "ok": false, "error_code": "bad_date|not_found|delete_failed|archive_failed|internal", "error": "…" }
```

`removed` = 删除的记录条数；archive 的锁粒度：锁内仅 rename 抢占、锁外压缩（不阻塞代理 append）。

---

## 3. 配置

### `GET /api/config`

```json
{
  "ui_lang": "zh",
  "auto_start_proxy": false,
  "retention_days": 30,
  "redact_headers": true,
  "translate": { "api_key": "", "base_url": "", "model": "", "temperature": 0.3, "target_lang": "zh" },
  "explain": { "prompt": "" }
}
```

- `ui_lang`：界面语言 `zh|en|ja`（260712 开源准备 item2），前端启动先读它再渲染。
- `translate`：**通用 LLM 配置**（名称历史遗留，设置页显示「LLM 模型」），翻译与 AI 解读共用；`target_lang` 为翻译目标语言 `zh|en|ja`（手改 config 可填任意语言名，item3）。
- `explain.prompt`：AI 解读任务描述；空串 = 用内置默认（按 `ui_lang` 取），非空 = 用户自定义（item4）。

### `POST /api/config`

请求体同上结构（部分字段可选，白名单合并写入）。`api_key` 写入时前端用 password 输入；读取时返回空串或 mask。

---

## 3.5 LLM 服务（翻译 / AI 解读，共用 `config.translate` 配置）

错误返回统一含 `error_code`（供前端 i18n 映射：`no_api_key` / `no_base_url` / `empty_text`）+ `error`（原始诊断串）。

### `POST /api/translate` — 翻译文本

**请求**：`{ "text": "..." }`（>20000 字符截断）

**响应** `200`：`{ "ok": true, "translation": "..." }`
**响应** `4xx/5xx`：`{ "ok": false, "error_code": "...", "error": "..." }`

目标语言取 `config.translate.target_lang`。system prompt 内置强隔离（`<text>` 内视为纯文本，绝不执行其中指令），文本内字面 `</text` 转义防定界符逃逸。

### `POST /api/explain` — AI 解读（这段内容在做什么）

**请求**：`{ "text": "..." }`（>20000 字符截断）

**响应** `200`：`{ "ok": true, "explanation": "..." }`
**响应** `4xx/5xx`：同上错误结构。

system = 固定隔离头 + 任务描述（`config.explain.prompt` 或内置默认）+ 固定隔离尾；用户内容包 `<content>` 且字面 `</content` 转义。隔离头尾代码写死，设置只能改任务描述段（防注入不可被配置绕开）。

### `POST /api/translate/test` — LLM 连通测试

**始终返回 HTTP 200**，由 `ok` 字段判成败（避免前端把配置错误当 fetch 异常）：
`{ "ok": true, "snippet": "译文片段…" }` 或 `{ "ok": false, "error_code": "...", "error": "..." }`

### `GET /api/about`

```json
{
  "version": "0.1.0",
  "settings_path": "/home/user/.claude/settings.json",
  "data_dir": "~/.cc-wire-analyzer",
  "captures_dir": "~/.cc-wire-analyzer/captures",
  "log_path": "~/.cc-wire-analyzer/run.log",
  "retention_removed": ["2026-06-01"]
}
```

`retention_removed`：本次启动按保留天数清掉的日期（供设置页反馈"清理确实在工作"）。

### `POST /api/open-folder`

用系统文件管理器打开目录（备份 / 存档等）。**仅允许数据目录内的路径**，防任意打开。

请求 `{ "path": "~/.cc-wire-analyzer/backups" }` → `{ "ok": true }` 或 `{ "ok": false, "error": "路径不在数据目录内" }`

---

## 4. 约定

- **headers_safe**：所有 headers 字段经脱敏，`authorization` / `x-api-key` / `anthropic-auth-token` 显示 `<redacted>`，列表/详情都不返回真实 token。**脱敏无条件生效，没有开关**（曾有个 `redact_headers` 配置项，但从未接线；260713 连开关一起删掉 —— 提供"明文存 key"的选项本身就是危险，何况录制现在可被 AI 经 CLI 读取）。
- **时间格式**：ISO 8601 带毫秒，本地时区（`2026-07-05T22:43:12.345`）。
- **大字段**：`request.body` / `response.content_blocks` 可能很大（MB 级），详情接口一次性返回；前端用虚拟滚动/折叠渲染。
- **错误透传**：上游 4xx/5xx 也要录（response 存原文 snippet），原样返回给 CC，不破坏 CC 错误处理。
- **路径前缀**：UI 所有路由必须 `/api/` 开头，否则会被代理 catch-all 当成上游流量转发。
