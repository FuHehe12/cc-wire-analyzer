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
  "backup_created": "~/.cc-wire-analyzer/backups/settings.json.20260705-224300"
}
```

孤儿恢复信息（上次崩溃未恢复、本次启动自愈）走 `GET /api/proxy/status` 的
`orphan_recovered_at_startup` 字段——只在 startup 时存在，start 接口不再返回死字段。

**响应** `409`（已在运行）：
```json
{ "running": true, "listen": "...", "error": "already_running" }
```

**响应** `500`（启动失败，settings.json 未被改）：
```json
{ "running": false, "error": "no_listen_port|patch_failed", "detail": "..." }
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
  "orphan_recovered_at_startup": null,
  "write_errors": { "count": 0, "last": null, "idx_count": 0, "idx_last": null },
  "external_change": null
}
```

- `orphan_recovered_at_startup`：若非 null，说明上次崩溃未恢复、本次启动已自动恢复，UI 应弹提示。
- `write_errors`（260713）：主文件写失败计数 + 索引写失败计数（独立）。非零说明磁盘满/权限/文件
  被锁——代理不阻塞转发但 UI 必须告警（"界面在跳盘上没字节"的静默数据丢失防护）。
- `external_change`（260717）：`null` 或 `{at, current, was_listen, original, detected_at}`。
  非 null 说明 cc-switch 或用户改了 BASE_URL——本工具已降旗（不再认为自己在 patch 态），
  UI 应提示"外部接管，点重新接管收编新上游"。

> **自检**：加新代理状态字段时，必须同步更新 `_proxy_state()` 函数（`src/app.py`）+ 此契约
> + `docs/AI_USAGE.md` 的 status 表 + 前端 `templates/index.html` 的 `refreshStatus()` 渲染。

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
  "translate": { "api_key": "", "base_url": "", "model": "", "temperature": 0.3, "max_tokens": 8192, "target_lang": "zh" },
  "explain": { "prompt": "" }
}
```

- `ui_lang`：界面语言 `zh|en|ja`（260712 开源准备 item2），前端启动先读它再渲染。
- `auto_start_proxy`（260713 接线）：启动软件时是否自动启动代理。
- `retention_days`（260713 接线）：捕获录制保留天数，启动期 `enforce_retention` 据此清理。
- `translate`：**通用 LLM 配置**（名称历史遗留，设置页显示「LLM 模型」），翻译与 AI 解读共用；
  `max_tokens`（260713 加）为长文本翻译/解读输出上限；`target_lang` 为翻译目标语言
  `zh|en|ja`（手改 config 可填任意语言名，item3）。
- `explain.prompt`：AI 解读任务描述；空串 = 用内置默认（按 `ui_lang` 取），非空 = 用户自定义（item4）。

> **历史字段**：`redact_headers`（260713 删除）—— 曾是脱敏开关，但代码从未消费；260713 连开关
> 一起删，脱敏改无条件恒开。老 config.json 里残留该键会被忽略。

> **自检**：加新配置字段必须三处都接通——`config.py::_DEFAULTS` 默认值 + 前端设置页 UI +
> 实际消费点。任何一处断了就是新的"死配置"（CLAUDE.md 教训①）。

### `POST /api/config`

请求体同上结构（部分字段可选，白名单合并写入）。`api_key` 写入时前端用 password 输入；读取时返回空串或 mask。

---

## 3.5 LLM 服务（翻译 / AI 解读，共用 `config.translate` 配置）

错误返回统一含 `error_code`（供前端 i18n 映射：`no_api_key` / `no_base_url` / `empty_text`）+ `error`（原始诊断串）。

### `POST /api/translate` — 翻译文本（SSE 流式，260713 改）

**请求**：`{ "text": "..." }`（>20000 字符截断）

**响应** `200` `text/event-stream`：

```
data: {"delta":"译"}
data: {"delta":"文"}
data: {"delta":"片段"}
...
data: {"done": true}

data: {"error_code": "...", "error": "..."}    // 错误时替代 done
```

- 增量字段 `delta`：流式译文片段，前端 rAF 节流拼接（单 textNode appendData，不堆 textNode）
- 结束字段 `done: true`：正常结束信号
- 错误字段 `error_code` + `error`：错误时替代 done，前端按 `error_code` 查 i18n 表（`no_api_key` / `no_base_url` / `empty_text` 等）

目标语言取 `config.translate.target_lang`。system prompt 内置强隔离（`<text>` 内视为纯文本，绝不执行其中指令），文本内字面 `</text` 转义防定界符逃逸。

### `POST /api/explain` — AI 解读（SSE 流式，260713 改）

同 `/api/translate` 的 SSE 协议（`delta` 增量 / `done` 结束 / `error_code` 错误），区别在 system prompt：

- system = 固定隔离头 + 任务描述（`config.explain.prompt` 或内置默认）+ 固定隔离尾
- 用户内容包 `<content>` 且字面 `</content>` 转义
- 隔离头尾代码写死，设置只能改任务描述段（防注入不可被配置绕开）

> **自检**：改 SSE event 格式时，必须同步改前端 `_streamResponse()`（`templates/index.html`）
> + 此契约 + `docs/AI_USAGE.md`。改隔离定界符时必须同步改 `_translate_parts` /
> `_explain_parts`（`src/app.py`）。

### `POST /api/translate/test` — LLM 连通测试

**始终返回 HTTP 200**，由 `ok` 字段判成败（避免前端把配置错误当 fetch 异常）：
`{ "ok": true, "snippet": "译文片段…" }` 或 `{ "ok": false, "error_code": "...", "error": "..." }`

### `GET /api/about`

```json
{
  "version": "<X.Y.Z from package metadata>",
  "settings_path": "/home/user/.claude/settings.json",
  "data_dir": "~/.cc-wire-analyzer",
  "captures_dir": "~/.cc-wire-analyzer/captures",
  "log_path": "~/.cc-wire-analyzer/run.log",
  "retention_removed": ["2026-06-01"]
}
```

- `version`：从打包元数据读（不发版每次手改）。
- `retention_removed`：本次启动按保留天数清掉的日期（供设置页反馈"清理确实在工作"，260713 接线）。

### `POST /api/open-folder`

用系统文件管理器打开目录（备份 / 存档等）。**仅允许数据目录内的路径**，防任意打开。

请求 `{ "path": "~/.cc-wire-analyzer/backups" }` → `{ "ok": true }` 或 `{ "ok": false, "error": "路径不在数据目录内" }`

---

## 3.6 配置体检（260718 方向 B / 260725 落地）

开代理前跑 8 条只读规则，回答"配置有没有矛盾"。三条铁律：**绝不写入** settings.json/凭据、
不提供自动修复（与 settings_guard 不变量③同源）；**宁可漏报不可误报**（误报比漏报更伤——
第二次误报之后横幅就再没人看）；**绝不把用户锁死**（error 级拦启动但必须留 `force` 逃生门）。

### `GET /api/health/config` — 配置体检结论

**响应** `200`：
```json
{
  "ok": true,
  "intent": "subscription",
  "patched": false,
  "issues": [
    {
      "code": "effort_max_rejected_upstream",
      "severity": "warning",
      "field": "env.ANTHROPIC_BASE_URL",
      "current_value": "https://api.anthropic.com",
      "hint": "effort=max at official endpoint → title/security requests 400 silently"
    }
  ],
  "scope": "settings_file",
  "scope_note": "Reads settings.json, not the running CC process environment."
}
```

字段说明：
- `ok`：无 error 级 issue 即 true（warning/info 不影响）
- `intent`：体检反推的用户意图。`subscription`=用官方订阅（BASE_URL 官方/空 + 无 token）、`third_party`=用第三方 token（有 token + BASE_URL 非 loopback/官方）、`unknown`=其余
- `patched`：是否处于本工具 patch 态（以 `.patched` marker 文件为准，穿透看 marker.original）
- `issues[].code`：规则 code，前端按 `dc.<code>` 查 i18n 表
- `issues[].severity`：`error`（拦启动）/ `warning`（横幅）/ `info`（仅抽屉）
- `issues[].field` / `current_value`：出问题的字段路径与当前值
- `issues[].hint`：英文短句给 AI；UI 不走 hint，自己查 i18n 表
- `scope` + `scope_note`：体检结论边界——读 settings.json 文件，不是 CC 进程环境（CC 启动时把 env 注入到进程，文件后来怎么改都不影响已起来的进程，体检天然改不了这个盲区）

**8 条规则枚举**（真源是 `src/doctor.py` 顶部的规则函数表）：

| code | severity | 一句话 |
|------|----------|--------|
| `half_switch_to_subscription` | error | BASE_URL 指第三方但无 token，OAuth 却在 |
| `dead_port_leftover` | error | BASE_URL 指本机端口但无人听 |
| `self_reference_state` | error | BASE_URL 指本实例端口但不在 patch 态 |
| `oauth_expired` | error | OAuth 过期 + 用订阅模式 |
| `effort_level_conflict` | warning | 顶层 effortLevel 与 env CLAUDE_CODE_EFFORT_LEVEL 矛盾（env 赢） |
| `effort_max_rejected_upstream` | warning | effort=max + 官方端点 → 标题生成等静默 400 |
| `oauth_expiring_soon` | info | OAuth 还剩 < 1 小时过期 |
| `token_overrides_oauth` | info | 同时有 OAuth 和 token（token 优先，多半你故意的） |

**`POST /api/proxy/start` 前置调用**：error 级 issue 拦启动，返回 409：
```json
{ "running": false, "error": "config_unhealthy", "health": <同 /api/health/config 出参> }
```
`POST /api/proxy/start?force=1` 越过 error 拦截（逃生门，规则可能错）。

> **自检**：加新规则必须三处同步——`doctor.py` 规则函数 + 此表 + `templates/index.html`
> 的 i18n 三语表（`dc.<code>` 键）。任一处断了就是规则有但用户看不到（界面回落到英文 code）。

---

## 3.7 失败聚合（260725 落地，**UI 未接**）

把当天失败按上游错误消息指纹归并（抹掉 request-id / uuid / 数字），每组摆请求侧字段。**只整理
数据不调 LLM**，分析交给外面 CC/agent（"人看 GUI、AI 走 CLI/API"的分工）。

### `GET /api/diagnose/errors?date=YYYY-MM-DD&limit=20` — 失败聚合

**查询参数**：`date`（可选，默认今天）、`limit`（默认 20，最大 200）

**响应** `200`：
```json
{
  "total_records": 2993,
  "failures": 2719,
  "groups": 7,
  "truncated": false,
  "items": [
    {
      "err_kind": "upstream_4xx",
      "status": 400,
      "message": "effort 'max' is not supported when thinking is disabled",
      "fingerprint": "a1b2c3d4",
      "count": 19,
      "first_ts": "2026-07-18T10:22:01",
      "last_ts": "2026-07-18T16:14:33",
      "kinds": { "title": 19 },
      "sessions": 1,
      "samples": ["req_xxx", "req_yyy", "req_zzz"],
      "req_fields": {
        "effort": "max",
        "thinking": "disabled",
        "model": ["glm-5.2", "glm-5v-turbo"],
        "stream": true,
        "max_tokens": 32000,
        "tools_n": [62, 75]
      }
    }
  ],
  "note": "req_fields: single value = uniform across group (possible cause); list = spans multiple values (rules out as cause)"
}
```

字段说明：
- `failures`：失败总数（`has_error` 或 status 非 2xx，两个都看）
- `groups`：归并后的真分组数（不受 limit 影响）
- `truncated`：items 是否被 limit 截断
- `items[].err_kind` / `status` / `message`：分组键 + 错误原文前 300 字
- `items[].fingerprint`：归一消息的 md5[:8]（人无意义，agent 可作稳定 key）
- `items[].count`：组内失败数
- `items[].first_ts` / `last_ts`：时间范围（判断是否持续/已停）
- `items[].kinds`：dict{kind→count}，组内涉及哪些请求类型（如 `{title:19}` = 全是标题生成失败）
- `items[].sessions`：涉及多少个不同会话（单会话偶发 vs 跨会话系统性）
- `items[].samples`：最多 3 条样本 rid，跟进到 `/api/captures/<id>` 看原始 record
- `items[].req_fields`：请求侧字段（model/effort/thinking/stream/max_tokens/tools_n）。
  **单值 = 全组一致 → 可能病因**；**列表 = 跨值 → 排除该字段当因**
- `note`：英文说明 req_fields 单值/列表语义，给 agent 看

**归并键** = `(err_kind, status, _fingerprint(err_msg))`，指纹归一规则：`req_[A-Za-z0-9]{6,}` →
`<request-id>`、UUID → `<uuid>`、4 位以上数字 → `<n>`、截 200 字。

**UI 未接入**（CLAUDE.md 待办③）：当前只有 API + CLI（`uv run python src/cli.py errors`）给
agent。人看的界面里还没有"今天失败都是些什么"的入口——这是 [界面导览.md](界面导览.md) P0
优化机会的来源。

> **自检**：改归并逻辑必须同步改 `diagnose.aggregate` + 此契约 + CLI `errors` 子命令。
> 加新 req_field 必须同步加到 `diagnose._req_fields` + `classifier.index_record` + 此契约
> + `IDX_SCHEMA` bump（防旧索引静默缺字段）。

---

## 4. 约定

- **headers_safe**：所有 headers 字段经脱敏，`authorization` / `x-api-key` / `anthropic-auth-token` 显示 `<redacted>`，列表/详情都不返回真实 token。**脱敏无条件生效，没有开关**（曾有个 `redact_headers` 配置项，但从未接线；260713 连开关一起删掉 —— 提供"明文存 key"的选项本身就是危险，何况录制现在可被 AI 经 CLI 读取）。
- **时间格式**：ISO 8601 带毫秒，本地时区（`2026-07-05T22:43:12.345`）。
- **usage 字段名双轨**（重要，易踩坑）：
  - **录制文件 `{date}.jsonl` 与 `/api/captures/<id>` 完整 record**：写 Anthropic 全名（`input_tokens` / `cache_read_input_tokens` 等）—— `proxy._parse_sse` 直写上游返回
  - **`/api/captures` 列表、`/api/dag` 节点、`/api/captures/stream` SSE 摘要**：归一后短名（`input` / `output` / `cache_read` / `cache_creation`）—— `classifier.index_record` 经 `usage_norm`（单一真源）转换
  - 前端 `templates/index.html` 自带 fallback（`ur.cache_read_input_tokens ?? ur.cache_read`）兼容两种形状，但**契约规定的列表/DAG 出参是短名**
- **lane_id 命名规则**：
  - 主线泳道：`s-<md5(session_id)[:8]>`（session_id 来自 `X-Claude-Code-Session-Id` 头，回落 `metadata.user_id` 内 session_id）
  - 子代理泳道：`agent-<md5(派生者id + 派生prompt前200字)[:8]>`（对齐命中时）或 `agent-<agent_fp>`（对齐未命中回落，agent_fp = system block[2] md5 短码）
  - 辅助调用：`aux`（所有会话的 title/security/count_tokens/compact/other 合一列）
- **kind 枚举**（真源 `src/classifier.py` 的 `KIND_ORDER`）：`main` / `subagent` / `title` / `compact` / `security` / `count_tokens` / `other`。完整语义见 [架构总览.md](架构总览.md) "2.1 分类与 DAG"。
- **err_kind 枚举**（真源 `src/proxy.py` 错误分类段）：`connect` / `timeout` / `http_error` / `upstream_4xx` / `upstream_5xx`。
- **大字段**：`request.body` / `response.content_blocks` 可能很大（MB 级），详情接口一次性返回；前端用虚拟滚动/折叠渲染。
- **错误透传**：上游 4xx/5xx 也要录（response 存原文 snippet），原样返回给 CC，不破坏 CC 错误处理。
- **路径前缀**：UI 所有路由必须 `/api/` 开头，否则会被代理 catch-all 当成上游流量转发。

> **本文档维护**：按 [文档维护策略.md](文档维护策略.md) 的 SSOT 原则——枚举真源在各模块
> docstring，本契约引用而不重复定义。改字段集必须 bump `IDX_SCHEMA` 并同步此契约 + AI_USAGE
> + 界面导览 + 架构总览四份文档的相关段。
