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
> + `docs/reference/AI_USAGE.md` 的 status 表 + 前端 `templates/index.html` 的 `refreshStatus()` 渲染。

### `GET /api/settings/upstream-history` — 上游配置历史（260807）

最近 5 套**真实上游**的 `ANTHROPIC_*` env 组合 + 当前是否处于「本机死地址」病态。

```json
{
  "ok": true,
  "max_items": 5,
  "items": [
    {
      "id": "b65d7c60",
      "at": "2026-08-07T14:22:03",
      "seen": 3,
      "base_url": "https://open.bigmodel.cn/api/anthropic",
      "keys": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_DEFAULT_OPUS_MODEL"],
      "env": {"ANTHROPIC_AUTH_TOKEN": "glm…1234", "ANTHROPIC_BASE_URL": "https://…", "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.2[1M]"},
      "has_token": true,
      "current": false,
      "token_match": true
    }
  ],
  "current": {"base_url": "http://127.0.0.1:5051", "is_local": true, "is_self": true,
              "recording": false, "needs_fix": true, "in_history": null}
}
```

- `id`：键值组合的内容指纹（sha1 前 8）。同一套配置反复切换只占一条。
- `base_url` 为 `null` = 官方订阅态（**根本没有 BASE_URL 键**），前端出专门文案，不要显示 "null"。
- `env`：**凭据类键已脱敏**（`前3…后4`），明文永不出接口。模型映射等非凭据键原样。
- `token_match`：凭据与当前配置相同但组合不同 = **同一个供应商的干净版本**，前端默认选中它。
- `current.recording`：代理是否正在 patch 态。前端据此决定「当前 BASE_URL」那行显示内存里的
  原上游（录制中）还是文件真值（未录制）——代理从未成功启动过时内存快照是空的。
- `current.needs_fix`：当前 BASE_URL 是本机地址**且代理没在录制** → 中了"本机地址被固化进
  切换工具的 profile"这个病（录制期间 cc-switch 保存 profile 所致，见 `docs/reference/AI_USAGE.md`
  「与 cc-switch 等配置工具共存」）。代理正在录制时本机地址是正常的，此字段为 `false`。

### `POST /api/settings/upstream-restore` — 一键还原（260807）

**请求**：`{"id": "b65d7c60"}`

把 settings.json 的 `ANTHROPIC_*` 命名空间**全量对齐**到该快照：删掉当前有而快照没有的键，
写入快照里的全部键。`OTEL_*`/`permissions`/`model` 等一律不动，行尾符保持原样，写前自动备份。
空集快照 = 把 `ANTHROPIC_*` 删干净，回到官方订阅原状。

**响应** `200`：
```json
{ "ok": true, "id": "b65d7c60", "base_url": "https://open.bigmodel.cn/api/anthropic",
  "added": [], "updated": ["ANTHROPIC_BASE_URL"], "removed": [],
  "backup": "~/.cc-wire-analyzer/backups/settings.json.20260807-234149.353",
  "current": {"needs_fix": false, "...": "..."} }
```

**错误**：`400 missing_id` / `404 not_found`（只接受本机采集过的 id，不接受任意 URL/token）/
`409 proxy_running`（录制中，此时 BASE_URL 本就该是本机地址）/ `400 self_reference` /
`500 write_failed`。失败路径一律**不碰 settings.json**。

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
      {"type":"tool_use","id":"toolu_xxx","name":"Read","input":{...}},
      {"type":"compaction","content":"..."}
    ],
    "chunks_count": 42
  },
  "error": null
}
```

**可选响应字段**（只在相应情况下出现，消费方不能假设一定有）：

| 字段 | 何时出现 | 含义 |
|---|---|---|
| `stop_sequence` | `stop_reason == "stop_sequence"` | 命中的是哪个停止序列。安全分类器的残缺输出（`<severity>8`）就是被它截断的 |
| `decode_error` | 响应体解压/解码失败 | 失败原因（`missing_codec:br` / `unknown_encoding:…` / `decompress_failed:…` / `utf8_decode_failed`）。**出现它就意味着同一条记录的 `body_text`/`usage`/`content_blocks` 不完整**——不是上游没返回，是我们没解出来 |

`content_blocks` 的 `type` 取值随上游协议扩展，不是封闭枚举。目前见过：`text` / `thinking` /
`tool_use` / `tool_result` / `server_tool_use` / `web_search_tool_result` / `compaction`。

`error` 非 null 时：
```json
{ "error": { "kind": "connect|timeout|http_error|upstream_4xx|upstream_5xx|stream_error", "status": 502, "body_snippet": "..." } }
```

> ⚠️ `stream_error` 的 `status` 是 **200** —— 错误藏在 SSE 帧里，HTTP 层看不出来。
> **判断一条请求是否失败必须看 `error`/`has_error`，不能只看 status**。

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
  "nodes": [{"id":"req_…","ts_start":"…","kind":"main|subagent|title|compact|security|count_tokens|quota_probe|hook_eval|other","lane":"s-<hash>|agent-<hash>|aux","model":"glm-5.2","status":200,"total_ms":4521,"usage":{...},"has_error":false,"summary":"…","turn_start":true,"tool_uses":2,"pure_chat":false,"turn":"s-<hash>#3","user_text":"（仅轮首）你这轮说了什么"}],
  "edges": [{"from":"req_…","to":"req_…","type":"seq|trigger|near"}],
  "lanes": [{"lane_id":"s-…","kind":"main|subagent|aux","first_ts":"…","count":3}],
  "turns": [{"turn_id":"s-<hash>#3","lane":"s-<hash>","head":"req_…","index":4,
             "first_ts":"…","last_ts":"…","node_ids":["req_…"],
             "user_text":"帮我把雷达的 betas 改成提升度…","partial":false,
             "origin":"user|synthetic|command|sdk|partial",
             "steps":12,"tool_uses":26,"total_ms":138000,"errors":1,"has_error":true,"pure_chat":false,
             "subagents":[{"lane_id":"agent-…","label":"你是视觉设计评审…"}],
             "aux":{"security":3,"title":1}}]
}
```

**`turns`（260802）——对话的语义单位，DAG 按轮折叠的数据源。** 轮＝一次用户消息 + 它引发的
全部工具循环步、派生的子代理、触发的辅助调用。分轮判据沿用 `turn_start`（最后一条 user 消息
含真实 text ＝ 用户新消息触发；全是 tool_result ＝ 中间步，260717 三天真实录制验证）。

| 字段 | 说明 |
|---|---|
| `user_text` | **这轮用户说了什么**。真源是索引的 `turn_user`（写时从完整 body 剥 `<system-reminder>` 后取 160 字）——不能读时拿 `last_user` 现剥：那字段只存前 2000 字，而 CC 注入的 reminder 可达 9960 字，剥出来常常是空的 |
| `partial` | 轮首不是真起点（代理中途启动，只录到某轮的中间段） |
| `origin`（260809，260810 加 `sdk`） | **这轮是谁发起的**：`user`（真人消息）/ `synthetic`（CC 自己合成的伪 user 消息，如建议补全/后台任务/离开回顾/内部检索）/ `command`（斜杠命令注入）/ `sdk`（程序驱动的会话）/ `partial`。判据单份在 `classifier._turn_origin`，前端不重算。**两类信号，优先级 partial > 措辞 > entrypoint**：`synthetic`/`command` 靠轮首文本前缀白名单——wire 层**没有结构性判据**（`tools_n`/`max_tokens`/计费头版本哈希在真人与伪轮间全重叠），措辞是唯一稳定指纹，故这一档是启发式；`sdk` 则读计费头的 `cc_entrypoint`，是**官方标识符**。命中不了的一律落回 `user`（宁可把伪轮当真轮，不能把真人消息弱化）。260810 用 CC 本地 jsonl 的 `promptSource` 做过 2,339 轮离线对账：一致率 99.8%，「把真人轮判成 synthetic」0 例。⚠️ `synthetic` **不是噪声**——伪轮会带出真工作、有真实 token 成本，前端只能降档显示，不能隐藏（藏了就是惯犯③静默丢数据） |
| `index` | 泳道内第几轮（从 1 起） |
| `errors` / `has_error` | 失败**条数**与布尔。给数量是因为「31 步里 1 次瞬时 429」和「整轮全挂」是两件事——前端据此决定标 ⚠N 还是整卡染红（一律染红会把红色用废：实测一天 68 轮有 29 轮含至少一次失败） |
| `subagents` | 这轮派生了哪些子代理（trigger 边起点落在本轮内）。嵌套派生天然成立：子代理派生的子代理归到父子代理的那一轮。`label` 取被派生泳道首条的用户文本＝派生 prompt |
| `aux` | 这轮触发的辅助调用计数（near 边起点落在本轮内）。⚠️ **只能归到主线的轮**：9 天 1290 条 aux 里带 `X-Claude-Code-Agent-Id` 的是 0 条，而 `session_id` 子代理与主线共用，wire 层没有任何标识能说「这次安全审查在审子代理的工具调用」。靠时序邻近猜属于启发式，与 §2.5「官方标识符优先」相悖，故不做 |

节点上对应多两个字段：`turn`（所属轮 id，aux 节点也有——它归属哪一轮）、`user_text`（仅轮首）。


**`sec_action`（可选，260730）**：仅 `kind=security` 的节点带，形状与 `/api/captures` 列表项的
`sec_action` 一致（`{tool, arg, truncated}`）。给前端渲染「审查：<待判定动作>」用——security 的响应
正文是 `<severity>8` 这类残片，拿它当 `summary` 等于没有摘要。其余 kind 不带此键（一天几千个节点，
不让它们各背一个恒 null 的字段）。

> **自检**：`_node_summary` 加字段必须同步这里 + 前端 `dagNodeHtml`。字段只对部分 kind 存在时，
> 明写「哪些 kind 带」——消费方不能靠试。

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
  "ui_scale": 100,
  "auto_start_proxy": false,
  "retention_days": 30,
  "translate": { "api_key": "", "base_url": "", "model": "", "temperature": 0.3, "max_tokens": 8192, "target_lang": "zh" },
  "explain": { "prompt": "" }
}
```

- `ui_lang`：界面语言 `zh|en|ja`（260712 开源准备 item2），前端启动先读它再渲染。
- `ui_scale`（260801 加）：界面缩放百分比，**读写两侧都夹在 80~200**（`config._clamp_scale`）。
  前端把它直接写进 `document.documentElement.style.zoom`——0 / 负数 / 天文数字会让界面缩没或
  撑爆，而这是个**改坏了就没法再打开设置页改回来**的字段，所以 `get_config` 与 `set_config`
  各夹一次，手改坏的 config.json 也救得回来。
- `auto_start_proxy`（260713 接线）：启动软件时是否自动启动代理。
- `retention_days`（260713 接线）：捕获录制保留天数，启动期 `enforce_retention` 据此清理。
- `translate`：**通用 LLM 配置**（名称历史遗留，设置页显示「LLM 模型」），翻译与 AI 解读共用；
  `max_tokens`（260713 加）为长文本翻译/解读输出上限；`target_lang` 为翻译目标语言
  `zh|en|ja`（手改 config 可填任意语言名，item3）。
- `explain.prompt`：AI 解读任务描述；空串 = 用内置默认（按 `ui_lang` 取），非空 = 用户自定义（item4）。

> **历史字段**：`redact_headers`（260713 删除）—— 曾是脱敏开关，但代码从未消费；260713 连开关
> 一起删，脱敏改无条件恒开。老 config.json 里残留该键会被忽略。

> **自检**：加新配置字段必须三处都接通——`config.py::_DEFAULTS` 默认值 + 前端设置页 UI +
> 实际消费点。任何一处断了就是新的"死配置"（[开发约定.md](开发约定.md) 惯犯 bug ①）。

### `POST /api/config`

请求体同上结构（部分字段可选，白名单合并写入）。`api_key` 写入时前端用 password 输入；读取时返回空串或 mask。

---

## 3.5 LLM 服务（翻译 / AI 解读，共用 `config.translate` 配置）

错误返回统一含 `error_code`（供前端 i18n 映射：`no_api_key` / `no_base_url` / `empty_text`）+ `error`（原始诊断串）。

### `POST /api/translate` — 翻译文本（SSE 流式，260713 改）

**请求**：`{ "text": "..." }`（>20000 字符截断，见下方 `input_truncated`）

**响应** `200` `text/event-stream`：

```
data: {"input_truncated": 20000, "orig": 53210}   // 可选，恒在最前
data: {"delta":"译"}
data: {"delta":"文"}
data: {"delta":"片段"}
...
data: {"truncated": "length", "max_tokens": 8192}  // 可选，紧邻 done 之前
data: {"done": true}

data: {"error_code": "...", "error": "..."}    // 错误时替代 done
```

- 增量字段 `delta`：流式译文片段，前端 rAF 节流拼接（单 textNode appendData，不堆 textNode）
- 结束字段 `done: true`：正常结束信号
- 错误字段 `error_code` + `error`：错误时替代 done，前端按 `error_code` 查 i18n 表（`no_api_key` / `no_base_url` / `empty_text` 等）
- **截断字段（260801 增量）**：`input_truncated`（本工具把原文砍到 `LLM_INPUT_MAX=20000` 才发出去，`orig` 是原长）与 `truncated`（上游 `finish_reason`，取值 `length` / `content_filter`，`max_tokens` 是发起时的本机设置）。两者都是**可选事件**，不出现即表示没发生。
  加它们的原因：「输出到此为止」有三种成因（原文被我们砍短 / 上游到 max_tokens / 内容审查），此前在界面上长得一模一样，用户改大 `max_tokens` 后无从判断生效没有（260801 用户反馈 #2）。`finish_reason` 此前只有非流式路径读，而翻译/解读走的恰恰是流式。

目标语言取 `config.translate.target_lang`。system prompt 内置强隔离（`<text>` 内视为纯文本，绝不执行其中指令），文本内字面 `</text` 转义防定界符逃逸。

### `POST /api/explain` — AI 解读（SSE 流式，260713 改）

同 `/api/translate` 的 SSE 协议（`delta` 增量 / `done` 结束 / `error_code` 错误），区别在 system prompt：

- system = 固定隔离头 + 任务描述（`config.explain.prompt` 或内置默认）+ 固定隔离尾
- 用户内容包 `<content>` 且字面 `</content>` 转义
- 隔离头尾代码写死，设置只能改任务描述段（防注入不可被配置绕开）

> **自检**：改 SSE event 格式时，必须同步改前端 `llmToolAction()`（`templates/index.html`）
> + 此契约 + `docs/reference/AI_USAGE.md`。改隔离定界符时必须同步改 `_translate_parts` /
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
  "retention_removed": ["2026-06-01"],
  "ai_guide": "/api/ai-guide"
}
```

- `version`：从打包元数据读（不发版每次手改）。
- `retention_removed`：本次启动按保留天数清掉的日期（供设置页反馈"清理确实在工作"，260713 接线）。
- `ai_guide`：自描述入口的路径（260801）。恒为 `"/api/ai-guide"`——它存在的意义是让只调过
  `about` 的 agent 不必先知道端点清单就能找到说明书。

### `GET|POST /api/snapshots/<sid>/analysis` — 骨架的 AI 语义层（260809）

`GET` 读已有结果（**不调模型**）：`{ok, exists, data}`。
`POST` 跑一次并覆盖落盘（"重新分析"就是再 POST 一次）：`{ok, data}`。

```json
{
  "sid": "snap_…", "created": "2026-08-09T19:20:00", "model": "deepseek-chat",
  "steps_total": 66,
  "turns": [{"turn": 1, "steps": [1,2,3], "title": "…", "intent": "…", "risk": ""}],
  "summary": "…",
  "dropped_steps": []
}
```

**这是分层设计，不是"AI 生成骨架"**：

| 层 | 谁产出 | 回答什么 |
|---|---|---|
| 事实层 | `snapshot_extract.level0()` 规则 | 有哪些步、谁触发、调了什么工具、轮次边界——可从录制原文复算 |
| 语义层（本端点）| AI | 这一轮在做什么、想达到什么、哪里值得注意 |

⚠️ **`turns[].steps` 里的步号在落盘前被强制校验**，不在程序骨架里的一律剔除并记入
`dropped_steps`。prompt 里要求"只引用真实步号"是要求，不是保证——**没有这道校验，
"AI 归纳挂在程序事实上"就只是一句说辞**：模型可以归纳出一轮根本不存在的步骤，
而界面照样渲染得像模像样。

其他边界：

- 只对 `kind=capture` 的快照有效（提示词快照没有轮次骨架），否则 400 `not_capture`。
- 抽不出步骤时 400 `no_steps`，不返回一份空归纳。
- 模型没给出可解析 JSON → `ok:false` + `bad_json`（HTTP 200），**如实说**而不是留空面板。
- 防注入照不变量 6：`SKELETON_GUARD_HEAD/TAIL` 硬编码不可配置，骨架经 `_wrap_content` 转义
  字面 `</skeleton>`。骨架里含用户原话与工具入参，是不可信内容。
- 结果存 `<sid>.analysis.json`，**不进快照信封**（信封不可改，这是可重算的派生物）；
  随快照删除一并清理，并计入 `size_of`。

### `GET /api/storage` — 数据目录占用（260809）

```json
{
  "data_dir": "~/.cc-wire-analyzer",
  "captures": {"bytes": 5088371174, "files": 15, "index_bytes": 68254423, "index_files": 15, "exists": true},
  "archives": {"bytes": 0, "files": 0, "exists": true},
  "snapshots": {"bytes": 2058509, "files": 10, "exists": true},
  "log_bytes": 5990734,
  "capture_days": 15,
  "largest_day": {"date": "2026-07-29", "bytes": 1183484730},
  "total_bytes": 5164674840
}
```

**只读**，不做任何清理动作（清理/归档是 `/api/captures/*` 那边的事）。

⚠️ **只 `stat`，绝不读文件内容**——这是这个端点的性能契约，不是实现细节：

| | 成本 | 随什么增长 |
|---|---|---|
| 本端点（scandir 取 `st_size`）| 稳态 **1.12 ms**（15 天 / 4.8 GB）| 文件数 |
| 数索引行数拿"条数" | 4.4 ms/天 | **数据量** |
| `config.list_capture_dates()` | 逐行读主文件 = 读 4.8 GB | 数据量，灾难级 |

所以**本端点不返回条数**：条数只能靠数行拿到，是唯一会让它随数据量变慢的字段。要按天的
条数请用 `/api/captures`（那里的分页本来就是为此设计的）。同理**不要**在这里调
`config.list_capture_dates()`。

`index_bytes` / `index_files` 只在 `captures` 里出现（其余目录没有索引文件，给它们带上两个
恒为 0 的字段就是死字段）。`{date}.idx.jsonl` 单列而不并入 `bytes`，因为它占 1.3%，
混进去会让"录制本身有多大"这个数失真。

### `GET /api/instance` — 本实例是谁（260809）

```json
{
  "port": 5051, "pid": 26924, "mode": "gui", "version": "0.4.11",
  "exe": "C:\\...\\cc-wire-analyzer-v0.4.11-windows.exe",
  "started_at": 1786000000.0, "recording": true,
  "data_dir": "~/.cc-wire-analyzer", "legacy": false
}
```

- `mode`：`gui` / `serve` / `dev`（源码 `uv run` 直跑）。由 `desktop.py` 在两个入口注入
  （`app.set_run_mode()`，形状同 `set_listen_port`）。
- `recording`：等价于 `proxy/status.running`（本实例是否正在 patch settings.json）。
- 这个端点必须**轻、无副作用、不依赖磁盘状态**——`/api/instances` 扫描时对每个候选端口调它。

### `GET /api/instances` — 本机在跑的所有实例（260809）

```json
{
  "instances": [ { "…同 /api/instance…": null, "is_self": true } ],
  "unknown_ports": [5055],
  "self_port": 5051,
  "scanned": {"start": 5051, "end": 5100}
}
```

扫 `5051-5100`（`find_free_port` 同一段）：TCP 探活 → `GET /api/instance` → 旧版本回退
`GET /api/about`（标 `legacy:true` / `mode:"unknown"` / `recording:null`）。端口开着但两个端点
都不应答 → 进 `unknown_ports`，**不猜它是什么程序**（同不变量 8「宁可漏报不可误报」）。

**四条边界，别放宽**：

1. **端口段硬编码，不接受任何入参**——可传就等于给出一个无认证的本机任意端口扫描器
   （同不变量 10 第 1 条：本机接口的入参就是攻击面）。
2. 只连 `127.0.0.1`，不解析主机名。
3. 纯只读：不写文件、不碰 settings.json、不动 marker。
4. 探测**必须绕过系统代理**（`ProxyHandler({})`）——本工具的用户十有八九开着本机代理，
   让探测走代理去连 127.0.0.1 轻则超时、重则把探测请求送出机器。

> **为什么不读 `port.txt` / `serve.pid`**：那两个文件单份、后写覆盖、无实例归属、退出不清理
> （260809 实测 `serve.pid` 停在六天前一个已退出的 PID）。本端点因此**不依赖任何持久化状态**，
> 也就不可能显示过期信息。写入侧的契约要不要改属 0.5.x，与本端点无关。

### `GET /api/ai-guide` — 自描述说明书（260801）

**不返回 JSON**：`Content-Type: text/markdown; charset=utf-8`，body 是 Markdown 原文。

结构固定为两段：

1. **本机运行期事实**（服务端现场生成）：`version` / 本实例实际监听地址 / 代理是否处于录制态 /
   数据目录 / 录制目录 / 被接管的 settings.json / 日志路径，全部是**绝对路径**。
   动机：文档正文写的是 `~/.cc-wire-analyzer/` 与"端口从 5051 起挑"，而调用方需要的是这台机器上
   的确切值。
2. **完整用法说明正文**：`docs/reference/AI_USAGE.md`，随产物打包（`build.spec` / `build-mac.spec` 的
   `datas`），冻结态从 `_MEIPASS/docs/` 读、源码模式从仓库 `docs/` 读。

**永不 500、永不空**：两条路径都取不到文件时回落到内置的最小速查（端点表 + 三条铁律），并在
`run.log` 记一条 warning。同一份正文也由 `cc-wire-analyzer --help` 打印。

### `POST /api/open-folder`

用系统文件管理器打开目录（备份 / 存档等）。**仅允许数据目录内的路径**，防任意打开。

请求 `{ "path": "~/.cc-wire-analyzer/backups" }` → `{ "ok": true }` 或 `{ "ok": false, "error": "路径不在数据目录内" }`

---

## 3.55 就地更新（260808）

**"点一下就换好"，不是"自动升级"**：没有定时检查、没有静默安装，每个端点都对应界面上的
一次点击。安全边界见 [开发约定.md](开发约定.md) 不变量 10（来源硬编码 / 逐跳 host 白名单 /
校验和有则必比、无则明说 / 半成品先落 `.part`）。

### `GET /api/update/check` — 查最新 release

只读，不写盘不下载。

```json
{
  "ok": true, "current": "0.4.10", "latest": "0.4.11", "has_update": true,
  "asset": {"name": "cc-wire-analyzer-v0.4.11-windows.exe", "size": 28311552,
            "url": "https://github.com/…/releases/download/v0.4.11/…"},
  "releases_url": "https://github.com/FuHehe12/cc-wire-analyzer/releases",
  "notes_url": "https://github.com/…/releases/tag/v0.4.11",
  "updates_dir": "~/.cc-wire-analyzer/updates",
  "phase": "idle",
  "can_apply": true, "apply_reason": "", "in_place": true
}
```

- 连不上 GitHub 时返回 `ok:false` + `error` + `releases_url`（**不是 500**）——网络不通是这个
  功能最常见的结局，一个手动下载地址比一个错误页有用。
- `phase` 是当前更新任务阶段（见 status）；下载/安装进行中 check **不会**把它盖回
  `idle`（260809 前会，前端轮询因此停表）。
- `asset` **按模式匹配**（`*windows.exe` / `*macos.zip`），不按固定文件名：资产名从 260808 起
  带版本号。没有本平台资产时为 `null`。
- `can_apply` / `apply_reason` / `in_place` 是**能力自陈**：源码运行 → `apply_reason:"source"`；
  macOS → `in_place:false`（只下载 + 校验 + 在访达指出，不替换运行中的 `.app`）。

### `GET /api/update/status` — 进度与阶段

`phase`：`idle` / `starting` / `downloading` / `verifying` / `ready` / `applying` / `error`。
`starting` = 下载任务已占位、线程尚未连上 GitHub（拉校验和清单 + connect 都在这个窗口，
走代理可达数秒）——260809 起独立于 `idle`，否则前端轮询把这个窗口当终态停表。
另有 `downloaded` / `total` 字节数、`path`（就绪后的本地文件）、`sha256`、
`sha256_verified`（是否与 release 的 `SHA256SUMS.txt` 比对过）、`error`。

### `POST /api/update/download` — 开始下载

立即返回 `{"ok": true}`，进度走 `status`。**单 flight**：任务在跑（`starting` /
`downloading` / `verifying` / `applying`）时重复调用返回
`{"ok": false, "already_running": true, "phase": "…"}`——这不是错误，
调用方应接着轮询 `status` 把进度接回去。校验和清单在下载线程内拉取；
校验不通过会删除文件并转入 `phase:"error"`。

### `POST /api/update/cancel` — 中止下载

`{"ok": true}`。半成品 `.part` 一并删除，状态回 `idle`（**不计为错误**）。

### `POST /api/update/apply` — 替换产物

成功：`{"ok": true, "in_place": true, "restart": true, "path": "…"}` —— 旧文件改名为
`<exe>.old`（下次启动清理），1 秒后拉起新版本并让本进程走正常退出路径（先恢复
settings.json）。macOS 返回 `in_place:false, restart:false` + 解压出的 `.app` 路径。

失败返回 **409** + `reason`：

| reason | 含义 |
|---|---|
| `not_ready` | 还没下载完 |
| `source` | 源码运行，没有可替换的产物 |
| `recording` | 代理正在录制。**不代劳停止**——停代理要写用户的 settings.json |
| `file_gone` | 下载好的文件不见了 |
| `not_writable` | 所在目录不可写（如装在 Program Files）。此时回落成"已下载，请手动替换" |
| `unpack_failed` | macOS 解压失败 |

### `POST /api/update/open-releases` — 系统浏览器打开发布页

**无入参**：地址是 `updater.py` 里硬编码的常量。做成无参而不是"打开某个 URL"，是因为后者
等于给出一个"用系统浏览器打开任意地址"的本机无认证接口。

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

## 3.7 失败聚合（260725 落地，260801 接入 UI）

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

**三个消费者**：API（agent）、CLI `errors`（`uv run python src/cli.py errors`，开发用）、
以及 260801 起的 **UI 折叠区**——捕获页状态卡下方一条"本日失败 N 条 → 归并为 M 组"的横幅，
展开后每组一张卡（`err_kind` / `status` / `count` / `kinds` / 消息 / `req_fields` / 样本 id 可点开详情）。
前端**只渲染不重算**：归并规则的单一真源在 `diagnose.py`，前端再实现一遍就是第二份会分叉的实现。
`req_fields` 的单值加粗、列表常规——这个视觉区分承载的正是诊断语义，改样式时别把它抹平。

> **自检**：改归并逻辑必须同步改 `diagnose.aggregate` + 此契约 + CLI `errors` 子命令。
> 加新 req_field 必须同步加到 `diagnose._req_fields` + `classifier.index_record` + 此契约
> + `IDX_SCHEMA` bump（防旧索引静默缺字段）。

### `GET /api/diagnose/trends?span=7&model=&kind=&limit=20` — 跨天失败趋势（260802）

单天 errors 的跨天版：最近 N 天失败用**同一归并键**跨天合并，加每日曲线 + 趋势标记 + 供应商 /
CC 版本切片。**只读、不调 LLM、不进 GUI**（维度爆炸，是 AI 审计甜区）。route 做 IO（按 span 算
日期 + 循环 `list_index`），`diagnose.trends(...)` 做纯归并。

**查询参数**：`span`（默认 7，1-30，最近 N 个日历日含今天，无录制日记 0 不跳过）/ `model` / `kind`
（精确过滤，AND）/ `limit`（默认 20，1-50）/ `exclude_session` / `session`（透传每日 `list_index`）。
日期列表由 `diagnose.span_dates(span)` 算，**route 与 CLI `trends` 共用**（两边各算一份就是下一次
`cache_creation` 式分叉）。

**响应** `200`：
```json
{
  "span": 7,
  "dates": ["2026-07-27", …, "2026-08-02"],
  "filters": {"model": null, "kind": null},
  "totals": {"records": 12345, "failures": 2805, "cross_day_groups": 2, "all_groups": 79},
  "per_day": [{"date": "2026-08-01", "records": 528, "failures": 12, "groups": 7}],
  "truncated": false,
  "items": [{
    "err_kind": "upstream_4xx", "status": 429, "message": "…", "fingerprint": "ab12cd34",
    "count": 5, "days_span": 5,
    "first_seen": "2026-07-18T…", "last_seen": "2026-08-02T…",
    "per_day": {"2026-07-18": 1, "2026-07-26": 1, "2026-08-02": 1},
    "trend": "recurring",
    "kinds": {"quota_probe": 5}, "sessions": 3, "samples": ["req_…"],
    "req_fields": {"model": "claude-sonnet-5", "host": "api.anthropic.com", "cc_version": "2.1.220"},
    "by_host": {"api.anthropic.com": 5}, "by_model": {"claude-sonnet-5": 5}, "by_cc_version": {"2.1.220": 5}
  }],
  "by_host":       [{"value": "api.anthropic.com", "count": 1820}],
  "by_model":      [{"value": "claude-opus-5",     "count": 1500}],
  "by_cc_version": [{"value": "2.1.220",           "count": 2790}],
  "note": "Cross-day failure groups (same key as /api/diagnose/errors, merged across days). …"
}
```

字段说明：
- `totals.cross_day_groups`：跨≥2 天的组数（复发信号）；`all_groups` = 全部去重组数
- `items[].days_span`：活跃天数；`per_day` 仅含活跃天 `{date:count}`
- `items[].trend`：**只描述形状**——`burst`（单天 ≥ `BURST_MIN`=50 次，事故）/ `sporadic`（单天少量）/
  `recurring`（稳态）/ `rising`（后半≥1.5×前半）/ `declining`（后半≤0.5×前半）
- `items[].days_since_last` + `stale`：**新鲜度，与趋势正交**。`stale=true`（距窗口末日 ≥3 天且非 burst）
  的组即使标着 `recurring` 也已经不在发生了——趋势看形状，新鲜度看时间，别用一个枚举同时表达两件事
- `items[].degenerate`：上游消息空洞（空串或 `Error`/`timeout` 这类裸词）。这类组的归并键**额外带
  host**（否则各供应商各原因的失败会并成一个没有诊断价值的垃圾桶组），且 `count`/`trend` 参考价值低，
  要判因得看 `samples`
- `items[].by_host/by_model/by_cc_version`：组内维度（值→count）；`by_host` 是**路由供应商**（wire 事实，
  非 model→vendor 推断——同 model 可能经多供应商/中转，host 才定得了供应商）
- `items[].req_fields`：含 host/cc_version（单值=组内一致，列表=跨值）
- 顶层 `by_host/by_model/by_cc_version`：全局切片（过滤后的失败请求，count 降序）
- 顶层 `by_local_loopback`：**本机回环 host 单列**，不混进 `by_host`——它不是供应商，通常意味着
  BASE_URL 自指（`doctor` 的 `self_reference` 规则管这个）或指向另一个本地网关。实测一次自指事故
  能占窗口失败总数的 95%，混在一起会把真实供应商分布彻底淹没
- `items` 排序：`days_span desc → count desc`（跨天复发优先于单天高频）

**归并键**同 errors：`(err_kind, status, _fingerprint(err_msg))`，跨天用同一键合并，不重新指纹。
**唯一的例外是退化消息**：`degenerate` 组的键追加 `host`。单天 `aggregate` 有意不这么做——一天之内
还能靠 samples 追，跨天跨供应商跨版本才需要拆。两处归并键的这处差异是有意的，不是分叉。

**新增 idx 字段**（`IDX_SCHEMA` 12→13）：`host`（`urlparse(upstream).netloc`，剥 userinfo 防 BASE_URL
带凭据）+ `cc_version`（`user-agent` 解析 `claude-cli/<ver>`，user-agent 不脱敏）。历史录制可回填
（rec.upstream / headers_safe.user-agent 一直存在），旧索引重建即生效。两者进 PUBLIC（**不进**
`_IDX_PRIVATE`），列表/SSE 摘要可见——审计相关小标量，`classify_idx` 不读它们（与 `session_id`
260802 移出 `_IDX_PRIVATE` 同决策）。

> **自检**：改跨天归并 / 趋势逻辑改 `diagnose.trends` / `_trend` + 此契约 + CLI `trends` 子命令
> + `diagnose_selftest.py` 第 8/14 段。host / cc_version 取法改要同步 `classifier._host_of` /
> `_cc_version` + `index_record` + 此契约。

---

## 3.75 检索与统计（260802 从 CLI 抽公共到 HTTP）

`grep` / `stats` 的核心逻辑在 `capture_store.grep` / `capture_store.stats`，**CLI 与 HTTP 共用
同一个函数**。历史教训：这两个能力最初只有 CLI，HTTP 侧缺失，于是 agent 被迫直读 jsonl
（违反 ai-guide 铁律①）；而 `stats` 漏 `cache_creation`（按 token 占比几个百分点、按成本占三到
四成）正是"CLI/HTTP 各抄一份"这条路的产物——抽公共就是为了不再有第二份。

### `GET /api/grep?date=&pattern=&in=all&limit=50&case=&fixed=&session=&exclude_session=`

在指定日期录制里搜文本。**读主文件**（要全文），所以会话过滤是逐条现算
（`classifier._session_id`，与索引里的取法同一个函数）。

响应：`{ok, date, pattern, in, hits, items:[{id, ts_start, kind, where, snippet, match_count}], coverage, note}`

- `coverage` = `{searched:[区域], skipped:[区域], skipped_ratio, note?}` —— **`hits:0` 必须连
  `coverage` 一起读**：0 命中与"根本没搜那块"在输出上曾经无法区分，agent 会把假阴性当否定证据用。
- `in` 可选 `all` / `system` / `user` / `assistant` / `sysmsg` / `tool_result` / `tool_use` / `tools`。
  **`all` 不含 `tools`**：工具定义每个请求全量重发（实测占请求体 44%），进默认集合等于让每条命中
  都混进同一份静态 schema。
- 正则错误 → `400 {ok:false, error:"bad_pattern", message}`。

### `GET /api/stats?date=&session=&exclude_session=`

响应：`{ok, date, records, file_size, kinds, models, statuses, errors, tokens{input,output,
cache_read,cache_creation}, cache_hit_ratio, total_ms{p50,p95,max}}`

- **走索引不走主文件**（260802）：要的字段全在 idx 里。原先逐行 parse 主文件、每条还调
  `classify(完整 record)`（等于把整条 `index_record` 重算一遍，含拿 ~108K 规则库匹配安全审查形状），
  826MB 的天要 ~9s，走索引 ~50ms。
- `cache_hit_ratio` = 读 ÷（读+写）；分母 0 给 `null` 而非 0——"没有缓存"≠"命中率 0%"。
- **不做美元换算**：单价随模型/链路/TTL 变，硬编码必然腐化。给全 token 数，换算交给使用者。
- `file_size` 是**当天整个文件**的大小，不随会话过滤变。

> **自检**：改检索区域 / 统计口径要同步 `capture_store._GREP_AREAS` / `grep` / `stats` + 此契约
> + CLI 对应子命令（同一函数，不必改两处逻辑，但参数要跟上）。

---

## 3.8 盲区雷达（260802）

聚合当天所有「已知集合外」的值——非标响应块类型/字段、未解析请求字段、非标 stop_reason/
thinking.type、没在基线里的 beta。**给 AI 当协议演进 / 录制盲区的改进入口**：一次调用拿到全部
盲区 + 样本 id + 归属，据此提改进（新增解析/渲染/分类规则，确认是标准的并入
`classifier.KNOWN_*`）。读 idx（`unknowns` 已在写时算好），不读主文件，比 stats 快。

### `GET /api/unknowns?date=YYYY-MM-DD&session=&exclude_session=` — 盲区雷达

**响应** `200`：
```json
{
  "ok": true,
  "date": "2026-08-02",
  "totals": {"records": 553, "with_unknowns": 1, "degraded": 2, "other_kind": 0},
  "blocks": [{
    "value": "tool_result", "count": 1, "samples": ["req_8e2a773"],
    "snippet": "{\"type\": \"tool_result\", \"tool_use_id\": \"call_1263c…\"}",
    "betas": [], "hosts": {"open.bigmodel.cn": 1}, "cc_versions": {"2.1.220": 1}
  }],
  "block_keys": [], "body_fields": [], "stop_reason": [], "thinking_type": [],
  "degraded": [{"value": "tool_use._input_raw", "count": 2, "samples": ["req_…"],
                "snippet": "{\"dimension\":\"…", "betas": [],
                "hosts": {"open.bigmodel.cn": 2}, "cc_versions": {"2.1.220": 2}}],
  "betas": {"new": [], "known": [{"value": "token-counting-2024-11-01", "count": 21}]},
  "other_kind_samples": [],
  "known": {"block_types": [...], "block_keys": {...}, "body_fields": [...],
            "stop_reasons": [...], "thinking_types": [...], "betas": [...]},
  "note": "已知集合（见 known）外的值 = 协议演进 / 录制盲区信号。**判读顺序**：① 先看 hosts…"
}
```

每维度 `[{value, count, samples[≤5 id], snippet, betas, hosts, cc_versions}]`，按 count 降序。

| 字段 | 含义 | 为什么是这个形状 |
|---|---|---|
| `hosts` | 该未知出现在哪些上游 host | **判读第一步**。单一第三方 host 独占 = 那个网关的形状差异，不是 CC 协议演进——照"协议演进"并进 `KNOWN_*`，会让官方链路真出现同名异构块时雷达反而哑掉 |
| `betas` | 与该未知**特异相关**的 beta，`[{value, lift}]` | 提升度 = 组内出现率 ÷ 全体基线出现率，只留 ≥ `UNK_BETA_LIFT_MIN`(1.5)。**空列表是正常结果**。裸计数做不到这件事：单次出现的未知所有 beta 都并列 1，`most_common` 退化成"取 header 里的前几个"；高频未知则被基线 100% 的那几个支配 |
| `snippet` | 值的前 ~80 字符 | 让 agent 一眼判断"这是哪类东西"，不必二次调详情 |
| `degraded` | **本工具自己的降级标记**（`_input_raw` / `input_raw_fallback`，见 `classifier.CAPTURE_ARTIFACT_KEYS`）| 性质与其余维度不同：那是 SSE 在 `content_block_stop` 前断了 / 工具入参拼不出 JSON，说明**这条录制的正文是残的**，要查代理侧不是上游。混在 `block_keys` 里会双向坏事——真协议信号被自己的噪声顶掉，而录制降级又被埋在"协议演进"的语境里没人管 |
| `betas.new` / `betas.known` | 分别是不在 / 在 `classifier.KNOWN_BETAS` 基线里的 | `new` 才是"CC 启用了新能力"的信号。原先全量按频次升序、称"长尾即信号"——实测每天把同样几个**结构性**低频的已知特性顶在最前（`structured-outputs` 只在标题请求带、`token-counting` 只在 count_tokens 探针带），低频与新出现是两回事 |
| `totals.with_unknowns` / `degraded` | 分开计数 | 否则 `with_unknowns` 会被本工具自己的噪声撑起来 |
| `other_kind_samples` | 固化 `quota_probe`/`hook_eval` 后仍落 `other` 的真未知（理想为空）| — |
| `known` | 当前已知集合基准（真源 `classifier.KNOWN_*` + `KNOWN_BETAS`）| 让 AI 判断「什么算未知」 |

**`KNOWN_BETAS` 的真源在 `classifier.py`**，前端由 `render_template(known_betas=…)` 注入消费——
260802 之前它只硬编码在 `index.html`，于是唯一会问"有没有新 beta"的消费者（AI 走本端点）拿不到，
只能退而按频次猜。

> **自检**：加新 kind 或扩充 `KNOWN_*` / `KNOWN_BETAS` 必须同步改 `classifier.py` + 此契约 +
> 架构总览 kind 列举 + 界面导览/报文解读的 kind 表 + `IDX_SCHEMA` bump + `cli_selftest.py`
> 的 `[1.5] 盲区雷达` 段。

---

## 3.9 快照：提示词/录制的备份、精确对比、思考链（260808）

**与 `POST /api/captures/clear` 的「压缩存档」不是一回事**：那个打包后**删掉原文件**，属于清理；
快照是用户显式保存的一份拷贝，**不删任何东西、不受 `retention_days` 自动清理**（同 `archives/`
的原则）。存放在 `~/.cc-wire-analyzer/snapshots/`，`index.jsonl` 是**可重建的缓存**而非事实源。

两类快照的元数据待遇不对称：

| kind | 信封 | 为什么 |
|---|---|---|
| `capture` | 极薄，事实全在 `payload`（完整 record）里 | record 本就含 id/ts/model/upstream/计费头/session_id，再存副本必然分叉 |
| `prompt` | 带四组元数据 `origin` / `src` / `ctx` / `fp` | 片段脱离上下文只是一坨文本，没有元数据就答不了"为什么这两段不一样" |

### `GET /api/snapshots?kind=prompt|capture` — 列表

返回信封（不含 payload）+ `usage`（占用总量，因为快照永不自动清理，堆积必须可见）+
`write_errors`。

### `POST /api/snapshots` — 备份

```json
{"kind": "capture", "record_id": "req_97f1e87", "date": "2026-07-28", "label": "", "tags": []}
{"kind": "prompt",  "record_id": "req_97f1e87", "where": {"kind": "system", "index": 2}}
```

`where` 三形态（**提示词不只在 `system` 里**——实测一条主线请求的指令来源有五处，
见 [同类工具构建手册.md](../methodology/同类工具构建手册.md)）：

- `{"kind": "system", "index": i}`
- `{"kind": "message", "index": i, "block": j}`
- `{"kind": "selection", "text": "…"}` — 界面上自由选中，位置不可定位

**响应** `200`：`{"ok": true, "snapshot": {…信封…}}`。

`prompt` 信封的关键字段：

```json
{
  "origin": {"where": "system[2]", "role": "system", "kind_hint": "cc_rules",
             "cache_control": "ephemeral", "sys_blocks": 3, "block_shape": [70, 57, 7024]},
  "src":    {"record_id": "req_…", "date": "2026-07-28", "ts_start": "…", "path": "/v1/messages"},
  "ctx":    {"model": "glm-5.2", "upstream": "open.bigmodel.cn",
             "harness": "claude-code/2.1.220.c26", "entrypoint": "cli", "wire_kind": "main",
             "is_subagent": false, "agent_fp": "5771d7ae", "session_id": "…", "beta": ["…"],
             "env": {"workspace": "D:\\Claude", "platform": "win32", "git_repo": false}},
  "fp":     {"sha256": "…", "norm_sha256": "…", "norm_rules": ["date"], "chars": 7024, "lines": 63}
}
```

`fp.norm_sha256` 是**抹掉日期/时间/UUID/长 hex 后**的哈希。没有它，CC 提示词里的当天日期会让
每天的快照两两都"有差异"，真正的变化淹没在噪声里。

### `GET /api/snapshots/<id>` — 完整快照（含 payload）

录制快照可达数 MB，与 `/api/captures/<id>` 同一性质：先看列表再取单条。

### `POST /api/snapshots/<id>/delete` — 删除（连同分析对话）

### `POST /api/snapshots/<id>/meta` — 改 `label` / `note` / `tags`

正文与元数据不可改——快照的价值就在于它不变。

### `GET /api/snapshots/diff?a=&b=&face=&context=3` — 精确对比

`face` 仅录制快照需要：`system` / `tools` / `messages`（默认 `system`）。
`messages` 面是**上下文腐烂的观测口**——同一条对话的两个时刻，早期历史有没有被改写或丢弃。
两个快照类型不同时返回 `kind_mismatch`。

**先揭示、再比对**：零宽字符、NBSP、全角空格、CR、行尾空白在进入比对前换成可见记号
（`⟨ZWSP⟩` 等），于是不可见的差异变成可见的字面差异。同形异码字符（撇号/连字符/全半角标点）
不改写，而是在行内字符级差异上打 `hg` 标——**CC 的中国用户字符水印正是这个形状**。

```json
{"ok": true, "diff": {
  "equal": false, "norm_equal": true,
  "counts": {"same": 59, "added": 0, "removed": 0, "changed": 4},
  "invisible": {"a": {}, "b": {"ZWSP": 1}},
  "homoglyphs": {"撇号": {"a": {}, "b": {"U+2019": 3}}},
  "hunks": [{"tag": "replace", "lines": [
     {"side": "a", "na": 12, "text": "…", "inline": [{"op": "replace", "a": "'", "b": "’", "hg": "撇号"}]}]}],
  "meta": {"ctx_diff": [], "origin_diff": [], "warnings": []},
  "truncated": false}}
```

`meta.warnings` 是**可比性护栏**：两个快照的 `agent_fp` / `wire_kind` / `model` / `upstream` /
`harness` 不同时提示"这两段本就不是同一类东西"，**提示但不阻止**——用户完全可能就是想比两类。

### `GET /api/snapshots/<id>/thinking?level=0|1|2&step=N&budget=` — 思考链（仅录制快照）

一条晚期请求的 `messages` 带着**整条对话到此刻的完整思考链**（实测最大 66 块 / 314,286 字），
而 LLM 输入上限只有两万——所以分层：

| level | 内容 | 默认预算 |
|---|---|---|
| `0` | 骨架：每步一行（触发者/思考量/工具/机械信号） | 20,000 |
| `1` | 摘要：每步思考首尾 + 信号，**按信号加权分配**篇幅 | 80,000（agent 档，`?budget=` 可覆盖） |
| `2` | 单步思考原文（需 `step=N`） | — |

产出**实测序列化尺寸后收缩**，`size` / `budget` / `over_budget` 如实报告；砍掉的东西一律有计数
（`omitted_steps` / `steps_without_excerpt` / `steps_total`）——"这步没摘录"不能被读成"这步没思考"。

**`availability` 分三档，没有思考链时也要给得出东西**：

```json
{"tier": "B", "reason_code": "disabled",
 "reason": "本次请求显式关闭了思考（thinking.type=disabled）",
 "steps": 12, "steps_with_thinking": 0, "thinking_chars": 0,
 "thinking_param": "disabled", "model": "claude-sonnet-5"}
```

- `A` 有思考链 → 三层全功能
- `B` 无思考链 → 附 `behavior` **行为链**（工具序列 + 反复证据：连续同工具、反复读同一目标、
  报错重试），并说出具体原因。实测 claude-sonnet-5 档 23/23 全部 `thinking=disabled`
- `C` `redacted_thinking` → 标注"上游加密不可读"，不试图解析

判档在**步**这一级做，不在模型级：`adaptive` 是主流形态，同一模型内部也会有的步不思考。

### `GET /api/snapshots/<id>/sources` — 多源指令清单（仅录制快照）

上下文冲突分析的原料。实测一条主线请求有五处在下指令（system 三块 + 用户 CLAUDE.md 注入 +
会话中 `role=system` 消息），外加工具描述（实测 81,911 字，是 system 的 13 倍）。
**内容相同的重复注入已合并计数**（`repeats` / `where_all`）——"同一条规则被重复注入 9 次"
本身就是一条值得看的事实。

### `POST /api/snapshots/diff/explain` — 让软件内的低成本模型对差异下结论（SSE 流式）

body `{a, b, face?}`。与 `/api/explain` 的区别是**输入是差异报告而不是原文**：两段 7K 提示词
加起来就顶到 `LLM_INPUT_MAX`，而"这些差异意味着什么"靠的是差异本身加元数据，不是把没变的
那几十行再读一遍。报告由后端拼（元数据对照 + 隐蔽差异计数 + 变化的行，按 `DIFF_BRIEF_MAX`
截断且**截断了会在报告里写明**）。两段完全相同时返回 `no_diff`，不浪费一次调用。
防注入沿用 `EXPLAIN_GUARD`——报告里全是从录制里抠出来的文本，同样是不可信数据。

### `GET /api/snapshots/<id>/chat` — 软件内 AI 的分析对话历史

外部 agent 也读得到：两条分析路径不互相隔绝，才不会各自从零开始。

### `POST /api/analyze/chat` — 软件内 AI 多轮分析（SSE 流式）

body `{sid, question}`。SSE 协议与 `/api/explain` 完全一致（`delta` / `done` / `error_code` /
`input_truncated` / `truncated`）。与它的三点不同，每点都是被"多轮"这件事逼出来的：

| | 单轮 `/api/explain` | 多轮 `/api/analyze/chat` |
|---|---|---|
| 内容 | 前端把文本发上来 | **后端从快照现算**（录制 → L1 摘要 + 多源清单；提示词 → 元数据 + 正文）|
| 防注入 | 一次性包 `<content>` | **每轮重拼 system guard**，内容只在第一条 user，用户提问包 `<question>` |
| 历史 | 无 | 落盘 `snap_xxx.chat.jsonl`，超 `CHAT_HISTORY_MAX` 丢最旧**并告知模型丢过** |

上下文**不落盘**：快照不可变，重算是确定的；落盘则每条 `chat.jsonl` 都被 20K 上下文撑爆，
而外部 agent 读 `/chat` 时想看的是对话本身。B 档快照的 system 里**写死禁止推测思考内容**
（附具体原因）——让模型自己判断有没有思考链不可靠，我们已经知道答案就该写死。

落盘时机是**回答产出之后**：没配 Key 这类连上游都没到的失败，不该在对话记录里留下一串
没人回答过的提问。中途出错时半截回答照样落盘，但会附上中断原因——半截存成完整，
下一轮模型会把它当作已说完的话接着推。

预算：`CHAT_CONTEXT_MAX=20000`（其中 `CHAT_SOURCES_MAX=4000` 给多源清单）/
`CHAT_HISTORY_MAX=12000` / `CHAT_QUESTION_MAX=4000`。

### `POST /api/snapshots/<id>/chat/clear` — 清空该快照的分析对话（快照本身不动）

### `POST /api/snapshots/clear` — 批量清理

body `{kind?, tags?, before?, sids?, preview?}`，条件之间是**「与」**；什么都不给 = 全部。
`preview: true` 只返回命中清单与可腾出的字节数，不删任何东西。

```json
{"ok": true, "preview": true, "count": 12, "bytes": 8421376,
 "items": [{"sid": "snap_…", "kind": "capture", "created": "…", "label": "…", "tags": []}]}
```

**两步走是有意的**：快照永不自动清理（`enforce_retention` 不碰 `snapshots/`），
所以手动出口必须存在；而按标签批量删不可撤销，一步到位的按钮迟早误伤。
单条失败不中断，失败的 sid 原样返回（`failed`）——删一半停下来，用户既不知道删了哪些、
也不知道还剩哪些。

### `GET /api/snapshots/<id>/brief?lang=zh|en|ja` — 给外部 agent 的现成指令（`text/plain`）

产出的**不是数据，是"让 agent 自己来取数据"的说明**：本机实际端口 + 端点清单 + 该快照的
元数据摘要 + 分析任务。按档位切换任务措辞——B 档**显式禁止推测思考内容**，因为只给行为记录
却让模型讲心理活动就是在诱导编造。

> **自检**：新增快照字段要 bump `snapshot_store.SNAP_SCHEMA` 并同步此契约 + AI_USAGE +
> 界面导览。快照文件本身永不因版本被丢弃，只有索引会重建。

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
  - 辅助调用：`aux`（所有会话的 title/security/count_tokens/compact/quota_probe/hook_eval/other 合一列）
- **kind 枚举**（真源 `src/classifier.py` 的 `KIND_ORDER`）：`main` / `subagent` / `title` / `compact` / `security` / `count_tokens` / `quota_probe` / `hook_eval` / `other`。`quota_probe`（CC 配额嗅探：`user="quota"`+maxtok=1）与 `hook_eval`（StopConditions hook 评估）260802 前落 `other`，现固化；其余未知形状仍落 `other`。完整语义见 [架构总览.md](架构总览.md) "2.1 分类与 DAG"。
- **err_kind 枚举**（真源 `src/proxy.py` 错误分类段）：`connect` / `timeout` / `http_error` / `upstream_4xx` / `upstream_5xx` / `stream_error`（HTTP 200 但 SSE 流内报错，260731 补）。
- **harness 声明面字段**（索引项，`IDX_SCHEMA=6` 起）：`beta`（`anthropic-beta` 拆成的特性数组——CC 声明启用了哪些协议扩展）/ `agent_id`（`x-claude-code-agent-id`，CC 给的子代理实例 ID）/ `ctx_mgmt` / `diagnostics` / `stop_seqs_n` / `thinking_budget`。这些是**发现录制盲区的信号源**，不是判别位——子代理判别仍以 system block[0] 计费头的 `cc_is_subagent` 为准（见 [开发约定.md](开发约定.md) 子代理判别定案）。
- **大字段**：`request.body` / `response.content_blocks` 可能很大（MB 级），详情接口一次性返回；前端用虚拟滚动/折叠渲染。
- **错误透传**：上游 4xx/5xx 也要录（response 存原文 snippet），原样返回给 CC，不破坏 CC 错误处理。
- **路径前缀**：UI 所有路由必须 `/api/` 开头，否则会被代理 catch-all 当成上游流量转发。

> **本文档维护**：按 [文档维护策略.md](../文档维护策略.md) 的 SSOT 原则——枚举真源在各模块
> docstring，本契约引用而不重复定义。改字段集必须 bump `IDX_SCHEMA` 并同步此契约 + AI_USAGE
> + 界面导览 + 架构总览四份文档的相关段。
