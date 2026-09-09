# API 契约（cc-wire-analyzer）

> 读者：改前端、写 agent 脚本、或对接这个工具的人和 AI。**触发时机：要调某个端点之前**。
> 本篇是**端点 / 字段 / 枚举的真源**——后端按此实现，前端与 agent 按此调用，改一侧要改两侧。
> `tools/checks/doc_audit.py` 机器对账「代码里有的端点这里有没有」。
> 配套：[AI_USAGE.md](AI_USAGE.md)（怎么用 agent 驱动它，比本篇更新得勤）/
> [界面导览.md](界面导览.md)（这些数据在界面上长什么样）/
> [开发约定.md](../development/开发约定.md)（改代码时不能破什么）。

所有 UI 路由前缀 `/api/`（代理 catch-all 不碰这个前缀）。返回 JSON，UTF-8，
响应头显式带 `charset=utf-8`（260909 补）。

**Windows 上读到乱码，八成不是响应的问题**（260909 实测）。JSON 响应体是 `\uXXXX` 转义的
**纯 ASCII**（实测 `/api/dag` 119 KB、非 ASCII 字节 0），按 GBK 还是 UTF-8 解出来完全一样——
乱码出在**客户端把解析后的中文打到本地码页的控制台**。解法在调用侧：PowerShell 先
`[Console]::OutputEncoding=[Text.Encoding]::UTF8`，Python 用 `python -X utf8` 或
`sys.stdout.reconfigure(encoding="utf-8")`。`charset=utf-8` 该补还是补了（`/api/ai-guide`
的 markdown 本来就带），但它治不了这个症状。

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
> + `docs/usage/AI_USAGE.md` 的 status 表 + 前端 `templates/index.html` 的 `refreshStatus()` 渲染。

### `GET /api/settings/upstream-history` — 上游配置历史

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
  切换工具的 profile"这个病（录制期间 cc-switch 保存 profile 所致，见 `docs/usage/AI_USAGE.md`
  「与 cc-switch 等配置工具共存」）。代理正在录制时本机地址是正常的，此字段为 `false`。

### `POST /api/settings/upstream-restore` — 一键还原

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
  "nodes": [{"id":"req_…","ts_start":"…","kind":"main|subagent|title|compact|security|count_tokens|quota_probe|hook_eval|notify_eval|self_prompt|other","lane":"s-<hash>|agent-<hash>|aux","model":"glm-5.2","status":200,"total_ms":4521,"usage":{...},"has_error":false,"summary":"…","turn_start":true,"tool_uses":2,"pure_chat":false,"turn":"s-<hash>#3","user_text":"（仅轮首）你这轮说了什么"}],
  "edges": [{"from":"req_…","to":"req_…","type":"seq|trigger|near"}],
  "lanes": [{"lane_id":"s-…","kind":"main|subagent|aux","first_ts":"…","count":3}],
  "turns": [{"turn_id":"s-<hash>#3","lane":"s-<hash>","head":"req_…","index":4,
             "first_ts":"…","last_ts":"…","node_ids":["req_…"],
             "user_text":"帮我把雷达的 betas 改成提升度…","partial":false,
             "origin":"user|synthetic|command|sdk|partial",
             "steps":12,"tool_uses":26,"total_ms":138000,"errors":1,"has_error":true,"pure_chat":false,
             "retry_n":0,"retry_cause":"",
             "subagents":[{"lane_id":"agent-…","label":"你是视觉设计评审…"}],
             "aux":{"security":3,"title":1}}]
}
```

**`turns`（260802）——对话的语义单位，DAG 按轮折叠的数据源。** 轮＝一次用户消息 + 它引发的
全部工具循环步、派生的子代理、触发的辅助调用。分轮判据沿用 `turn_start`（最后一条 user 消息
含真实 text ＝ 用户新消息触发；全是 tool_result ＝ 中间步，260717 三天真实录制验证），
外加一条**重试重发合并**（260904，见 `retry_n`）。

| 字段 | 说明 |
|---|---|
| `user_text` | **这轮用户说了什么**。真源是索引的 `turn_user`（写时从完整 body 剥 `<system-reminder>` 后取 160 字）——不能读时拿 `last_user` 现剥：那字段只存前 2000 字，而 CC 注入的 reminder 可达 9960 字，剥出来常常是空的 |
| `partial` | 轮首不是真起点（代理中途启动，只录到某轮的中间段） |
| `origin`（260809，260810 加 `sdk`） | **这轮是谁发起的**：`user`（真人消息）/ `synthetic`（CC 自己合成的伪 user 消息，如建议补全/后台任务/离开回顾/内部检索）/ `command`（斜杠命令注入）/ `sdk`（程序驱动的会话）/ `partial`。判据单份在 `classifier._turn_origin`，前端不重算。**两类信号，优先级 partial > 措辞 > entrypoint**：`synthetic`/`command` 靠轮首文本前缀白名单——wire 层**没有结构性判据**（`tools_n`/`max_tokens`/计费头版本哈希在真人与伪轮间全重叠），措辞是唯一稳定指纹，故这一档是启发式；`sdk` 则读计费头的 `cc_entrypoint`，是**官方标识符**。命中不了的一律落回 `user`（宁可把伪轮当真轮，不能把真人消息弱化）。260810 用 CC 本地 jsonl 的 `promptSource` 做过 2,339 轮离线对账：一致率 99.8%，「把真人轮判成 synthetic」0 例。⚠️ `synthetic` **不是噪声**——伪轮会带出真工作、有真实 token 成本，前端只能降档显示，不能隐藏（藏了就是惯犯③静默丢数据） |
| `index` | 泳道内第几轮（从 1 起） |
| `retry_n` / `retry_cause`（260904） | 这一轮里同一句 prompt 被**原样重发**了几次，以及原因（取失败节点里最常见的那条错误说明，给轮卡 tooltip）。上游过载时 CC 会重发同一句，每次都是合法轮起点——实测 09-03 一条泳道 10 个轮首全是同一句、一分钟内，wire 因此比 jsonl 多切 18 轮。合并判据三条同时成立：轮首与它同一句（归一空白后全等）、上一次 `has_error`、间隔 ≤60 秒（按链传递）。**合并不是丢弃**：重试节点全留在轮里当中间步（`steps` 照数、展开可逐次看），与 `[Image:` 那批"归回原轮"同一口径。**与 `errors` 是两件事**：那是"这轮里失败了几次"，这是"这句话发了几遍" |
| `errors` / `has_error` | 失败**条数**与布尔。给数量是因为「31 步里 1 次瞬时 429」和「整轮全挂」是两件事——前端据此决定标 ⚠N 还是整卡染红（一律染红会把红色用废：实测一天 68 轮有 29 轮含至少一次失败） |
| `subagents` | 这轮派生了哪些子代理（trigger 边起点落在本轮内）。嵌套派生天然成立：子代理派生的子代理归到父子代理的那一轮。`label` 取被派生泳道首条的用户文本＝派生 prompt |
| `aux` | 这轮触发的辅助调用计数（near 边起点落在本轮内）。**子代理的轮也会有**（260902）：安全审查的被审对象由请求正文判定——transcript 首条 user 就是那次 Task 的派生 prompt。头上没有这个信息（CC 把 side query 的 agent 身份写死成 main，实测 aux 带 `X-Claude-Code-Agent-Id` 0/1236）。其余辅助 kind 仍一律归主线，那是实测结果不是保守：它们在 CC 里就是主循环独占的 side query |

节点上对应多两个字段：`turn`（所属轮 id，aux 节点也有——它归属哪一轮）、`user_text`（仅轮首）。


**`sec_action`（可选，260730）**：仅 `kind=security` 的节点带，形状与 `/api/captures` 列表项的
`sec_action` 一致（`{tool, arg, truncated}`）。给前端渲染「审查：<待判定动作>」用——security 的响应
正文是 `<severity>8` 这类残片，拿它当 `summary` 等于没有摘要。其余 kind 不带此键（一天几千个节点，
不让它们各背一个恒 null 的字段）。

> **自检**：`_node_summary` 加字段必须同步这里 + 前端 `dagNodeHtml`。字段只对部分 kind 存在时，
> 明写「哪些 kind 带」——消费方不能靠试。

### `GET /api/actions?date=YYYY-MM-DD&lane=…&since=0` — 上下文账本（外环观测者用）

把一条录制流还原成**外环观测者**能直接读的对话全文。外环观测者 = 另开一个独立的 AI，
跟踪被观测 agent 做了什么、在做什么、接下来要做什么。

**为什么另开一个端点**（260908 实测，样本 `2026-09-06` 的 54 步主线）：

| 给法 | 体积 | 约 token |
|---|---:|---:|
| 逐条 `/api/captures/<id>` 拉全量 | 19.8 MB | 5,255k |
| 本端点（去重后全文，含 tools/system） | 377 KB | 101k |
| **本端点默认（去重后全文，只给工具名）** | **241 KB** | **68k** |

那 19.8 MB 里 **6044 条消息是重复重发的，唯一的只有 292 条** —— CC 每次请求把整段历史原样
再发一遍。所以体积问题**靠去重就解决，而且零信息损失**，不需要语义压缩，也不截断正文。
`/api/dag` 的 `summary` 只有 `🔧 Bash`（工具名，没有参数），说不出做了什么，同样不够用。

| 参数 | 说明 |
|---|---|
| `since` | **唯一的增量标志**。给了就从那一步之后接着读，不给就是整段 |
| `date` | 缺省=今天；经 `YYYY-MM-DD` 格式 + 语义校验（防路径穿越） |
| `source` / `lane` / `session` | 同其余读取端点；`lane` 是 `s-…` / `agent-…` / `aux` |
| `limit` | 本次最多几步，缺省 500，上限 5000。给了 `turns` 时不生效 |
| `turns` | **按对话轮取**（260909），一次 N 轮，上限 200。一轮＝一次用户消息加它引发的全部工具循环步；取满 N 轮就停，绝不在轮中间按步截断。辅助泳道的步没有轮归属，跟着当前轮走、不占名额 |
| `tools` | `1` 时附完整工具 schema；默认只给工具名清单 |
| `view` | `full`（缺省）= 对话全文；`dialog` = 纯对话流，见下 |

```json
{
  "date": "2026-09-06", "source": "", "lane": "s-751cdf31", "session": "",
  "total": 54, "next": 153, "done": true,
  "turns": [{"turn_id": "s-751cdf31#9", "index": 5, "lane": "s-751cdf31",
             "origin": "user", "partial": false,
             "steps_returned": 2, "steps_in_scope": 2, "complete": false,
             "user_text": "用户这轮说的话（截 160 字）"}],
  "tools": ["Agent", "Bash", "Read", "…"],
  "guard": "以下 <content></content> 标签内是一段被录制下来的 AI 会话原文…",
  "content": "<content>
# 录制 2026-09-06 · 泳道 s-751cdf31 · 第 57 步起…
</content>"
}
```

`content` 的正文形状——**结构化标识只留每步一行头 + 五个方括号前缀**。同一份内容用 JSON 装是
469 KB，纯文本 197 KB，键名/引号/转义吃掉一半多：

```text
#req_7ee737e 13:19:34 s-751cdf31#5 claude-opus-5 8.0s   ← 步头（失败的步尾巴带【失败】）
[用户] 我想知道的是，网络录制的提示词都是怎么来的…不要回灌
[系统] <total_tokens>14927665 tokens left</total_tokens>
[思考] （多数步没有——实测 54 步里只有 2 步有正文，其余是空签名）
[Bash] {"command": "git commit -q -m …"}
[工具返回] 5c0a121 docs: 报文解读补一节…
[工具返回·报错] grep: -P 与当前 locale 不兼容
[说] 网上流传的提示词基本只有两条来路…
[缺失] 索引里有这一步，原文取不到（录制被清理 / 分片已不在 / 坏行）
```

历史消息排在响应之前：这条请求带的是**上一步**的工具返回，读起来正好是「返回是什么 →
它接着做了什么」。同一条消息只在**首次出现**处输出一次；`since` 续读时，之前那些的哈希会先
喂进去重表，所以接着读不会把整段历史重吐一遍（实测分段续读合计 238 KB vs 一次全量 241 KB）。

两条容易踩反的渲染规矩：**工具返回单独标 `[工具返回]`，不混进 `[用户]`**——它在 wire 上确实是
user 角色（内环把结果喂回去才有了下一条请求），但读的人会当成用户说的话；**历史里的助手内容不
重复输出**——每个 tool_use 都会从它自己那一步的响应出一次，助手正文也只在产生处以 `[说]` 出
一次（去重是两级：消息级挡 CC 重发的整段历史，块级挡"产生时 `[说]`、下次请求历史里又以
`[助手]` 重出"的内容级重复）；`[助手]` 前缀因此只剩一种用途：**录制开始之前**的历史助手正文
（产生它的响应从未被录到）。

**`view=dialog`（260908）**：同一份管线换一张视图——只要 `[用户]` / `[说]` / `[思考]` 与
**每步一行工具摘要**，工具的输入输出明细全部剥掉。给"读懂这段会话讲了什么"的分析用
（实测 311 步真实泳道：full 6.0 MB / 4 页 → dialog 222 KB / 1 页）。形状：

```text
#req_d8ac254 20:37:07 s-1a11ec45#7 claude-opus-5 39.1s
[用户] 继续这个项目吧，还有一些地方需要修正…
[说] Now实现后端改判。
#req_e07f48f 20:43:04 s-1a11ec45#7 claude-opus-5 11.8s
[用了 Edit] src/classifier.py
[用了 Edit] src/app.py
[说] near 边挂接完成。
```

规则：摘要行取工具输入里最能标识对象的字段首行（Bash→`command`、Edit/Read→`file_path`、
Grep→`pattern`、`Task`→`[派生子代理] {description}`，截 80 字符）；子代理以**自己泳道的对话**
出现（步头带泳道名），不靠主线里的 Task 返回正文；`<system-reminder>` 与
`<local-command-stdout>` 从用户消息里剥掉，`<command-name>`（/compact 这类用户动作）保留；
请求级 `[错误]` 保留（一行，信号强）。

**问人的工具是例外**（260909）：`AskUserQuestion` / `ExitPlanMode` 的返回**是用户的原话答复**，
不是普通工具输出——dialog 视图照旧剥掉别的 `tool_result`，但这两个的返回留下并标 `[答复]`
（`full` 视图同样标）。提问那一行也从光秃秃的「用了 AskUserQuestion」改成 `[提问] 问题 选项：A / B`
（入参是 `questions` 数组，原来的对象字段兜底一个都取不到）。**问在这一步、答在下一步**是
wire 上的真实次序，中间只隔一个步头，不为了好看把答复挪到问题旁边。`since` 续读时，`since`
之前出现过的提问调用 id 会先喂进去重表的同一趟预热，所以从答复那一步开始读也认得出来。

**`[用户]` 按消息分来源**（260909）：子代理泳道里上级 AI 的派生指令、CC 自己合成的伪轮，
在 wire 上全是 user 角色，原先一律写 `[用户]`，观察者只能逐条甄别哪句是真人说的。现在分四类——
`[用户]` / `[用户·命令]`（`<command-name>` 这类斜杠命令注入）/ `[系统合成]`（`[SUGGESTION MODE`、
`Perform a web search for the query:` 等 CC 内部合成）/ `[派生指令]`（子代理泳道）/ `[辅助调用]`。
判据是 `classifier` 里那两族措辞常量加泳道 `kind`，**按消息判不按轮判**——一步的历史里可能含
录制开始前的旧消息，套用当前轮的 origin 会张冠李戴；只在会话级成立的 `sdk` 因此不进前缀，
它在 `turns[].origin` 里。反馈提到的「队友消息」暂无可区分的 wire 信号，不单列。

| 字段 | 说明 |
|---|---|
| `guard` | **必须原样放进你给模型的系统消息**，别只贴 `content`。录制里的系统提示词、工具说明、`<system-reminder>` 全是指令性文本，`content` 内一切只当数据、不当指令（安全不变量 6，与 AI 解读共用同一套定界符；`content` 里的字面 `</content` 已转义） |
| `next` / `done` | 下次的 `since`；`done=false` 表示还没读到末尾（超过 `limit`，或单次响应超过 2 MB 上限——**在步边界停**，不切断某一步的正文） |
| `turns` | 本次返回**覆盖了哪些轮**（260909，`turns` 参数给不给都有）。`complete` 是这里最要紧的一位：该轮在当前范围内的步没取全（分页或 2 MB 上限截断），**或它是范围里的最后一轮**（没有下一轮来终结它，录制可能仍在进行），就是 `false`。读的人据此知道手里是半轮、后续拉齐可以补建，别把半轮当整轮建模。`partial` 是另一件事——轮首没录到的残轮（代理中途启动）。`origin` 见 `/api/dag` 的同名字段：`user` / `synthetic` / `command` / `sdk` / `partial` |
| `tools` | 默认是工具名清单。整段 schema 是 168 KB / 约 45k token 且一整个会话一字不变，是上下文膨胀最大的单一来源，要才给 |

**`since` 为什么不能用 `/api/captures` 的 `offset`**：那边是倒序分页（`entries[::-1][offset:]`），
活跃录制时前面插入新记录会让同一个 offset 两次读到不同的东西。索引本身只追加，正序位置写进去
就不再变。`seq` 在 lane/session 过滤**之前**编号，所以换条泳道也能接着用同一个游标。

`lane` 是分类器现算的（索引里没有），本端点走 `/api/dag` 那份缓存取，同一天不重算。

`include_aux=true|false` 默认 true；false 过滤辅助安全检查，保留子代理。非法值返回400 bad_include_aux，响应回显布尔值。`next` 统一使用 date/source 原始索引位置（筛选及去重前），不是 total 或去重计数；空增量 done:true 保持 next，不重新读历史。每步标题标注真实“泳道=ID”。session 范围推荐 view=dialog&include_aux=false，日期/来源/筛选范围变化须分别维护水位。

### `GET|POST /api/observations` — 外环观测状态（一个路径两个方法）

外环观测者维护的清单存在这里。**内环**是被观测的 agent 自己那圈；**外环**是另开的一个 AI，
读 `/api/actions` 拿会话全文，判断完把结论小批量写回来。CCWA 负责事实、持久化与显示，
**不跑模型**——事实由程序产出，AI 只解释意义。界面上是「实时分析」标签页。

**`GET`**：不带 `id` 列全部（摘要，不含条目正文）；带 `id` 取一份完整状态；`GET /api/observations/<id>` 是同义单观测入口，不落入上游代理。

列表每行除 `id/title/scope/revision/cursor/updated/n_items/n_retracted` 外还有 `preview` 与 `has_flow`。`preview` 是 60 字以内的一句话摘要，按 `current.understanding` → `anchor.user_text` → 首条未撤回条目正文回落，只从已保存内容里取，不新生成说法；`title` 可省，界面靠它把同一天的多条观测区分开。

列表另接受 `rid`（配合 `date` / `source`）：把一条录制请求解析成它所在的范围，额外返回 `capture_scope:{date,source,lane,session}` 与 `matches:[观测 id]`。泳道取自当天 DAG；辅助调用（`aux` 泳道）改用同会话主线的泳道，否则它不属于任何一场对话。匹配规则是「观测范围里的空字段表示不限制」，只有两边都非空且不相等才排除；泳道精确匹配的排在最前。解析失败或认不出，仍返回 `capture_scope` 与空 `matches`，不猜。

**`POST`**：body 不带 `id` = 新建（`{scope:{date,source,lane,session}, title}`，返回含 `id`）；
带 `id` = 提交一批操作；带 `delete:true` = 删除。

```json
{"id":"obs_ba645ca","submission_id":"客户端生成的唯一串","base_revision":12,
 "ops":[{"op":"add_item","kind":"finding","text":"seq151 起换了模型…",
         "evidence":["req_ba6f13a"],"status":"supported","client_ref":"f1"},
        {"op":"link_items","from":"f1","to":"i_cec8f9","type":"belongs_to"},
        {"op":"update_item","id":"i_cec8f9","patch":{"status":"supported"}},
        {"op":"retract_item","id":"i_9f31aa","reason":"证据不足"},
        {"op":"rebuild_goal_flow","id":"i_cec8f9","reason":"首版把两件交付并成一个任务","goal_flow":{"anchor":"…","iterations":"…"}},
        {"op":"set_cursor","cursor":153}]}
```

| 字段 | 说明 |
|---|---|
| `submission_id` | **不能省**。外环是另一个进程，超时重试是常态；同一个 id 重放原样退回当前状态、不重复建条目（响应 `replayed:true`） |
| `base_revision` | 对不上返回 **409**，body 里连当前 `state` 一起给——只回一句「版本不对」的话，调用方还得再拉一次才能合并。不给这个字段则跳过版本检查（首版单写者的便利口子） |
| `client_ref` | 观测内持久唯一名称，当前批后续操作及后续批次可直接引用；不允许 i_ 前缀或首尾空格。响应 `refs` 仅列本批创建的名称，完整映射在 `state.refs`。重复新建返回 duplicate_ref；历史重名返回 ambiguous_ref，需改用真实 ID；流水截断不删除已持久名称 |
| `kind` | `goal` 目标 / `phase` 阶段 / `artifact` 产物 / `check` 核验 / `finding` 发现 / `open` 未决 / `prediction` 预测 / `deviation` 偏差 |
| `status` | `tentative` 待证 / `supported` 有据 / `unresolved` 未解 / `retracted` 已撤回。**与被观测工作的进度分开**——不能用一个 done 同时表示「任务结束」和「结论正确」 |
| `type`（关联） | `belongs_to` / `depends_on` / `produces` / `supports` / `contradicts` |
| `evidence` | `req_` 开头的步号，界面上可点回那条请求 |
| `cursor` | 外环自报读取水位；建议写入 `/api/actions` 响应的 `next`，续读时用作 `since`。它属于当日索引坐标，不是当前泳道已执行的步数。界面单独显示外环多久没有更新 |

三条硬要求，都由 `tests/observe_selftest.py` 守着：

1. **幂等**——同 `submission_id` 重放不增条目、不推进 `revision`。
2. **事务**——一批里有任何非法操作则整批不生效，合法的那几条也不写进去；提交流水与状态在同一次
   原子替换里落盘，不会出现「水位前移了、状态没保存」。
3. **改判回改原条目并留痕**——`update_item` / `retract_item` 把旧版压进 `history`（留最近 20 版）。
   只追加不回改，最新结论会被埋在中间。

存储是 `~/.cc-wire-analyzer/observations/<id>.json`，原子替换。与原始录制隔离：不覆盖
`.analysis.json` / `.semantic.json`，也不塞进 snapshot note。

#### 严格写入与紧凑响应

操作字段为：add_item = op/client_ref 加条目字段；update_item = op/id/patch（非空对象）；retract_item = op/id/reason（可选字符串）；link_items = op/from/to/type/remove；set_cursor = op/cursor（必填非负整数）；rebuild_goal_flow = op/id/reason（必填非空）/goal_flow。条目字段为 kind/text/status/evidence/title/progress/covers/cover_span/forecast/goal_flow/goal_iteration，其中 cover_span 仅由 HTTP 展开。text 最多4000字符、evidence 最多50项、reason 最多1000字符、观测/条目 title 最多200字符；超限明确拒绝，不截断。旧状态读取与省略字段的更新不重验旧值。未知字段或非法类型一律400，detail 指明错误；无效整批不写状态、水位、history 或 submission。重复写相同值、添加已存在关系仍允许成功。新建与提交外壳也拒绝未知字段、非对象 JSON；base_revision 如提供须为非负整数。

`update_item.patch` 另接受写入专用的 `goal_flow_delta`，不能用于 add_item，不保存为条目字段；与同一 patch 中的 goal_flow 互斥。合并规则见下方「A→G 小增量写入」。

`rebuild_goal_flow` 整份替换某个 goal 条目已有的 goal_flow，用于外环第一次把 A→G 建歪、或旧观测结构过时需要按原始录制重做的情况。`reason` 必填、非空、最多1000字符；`goal_flow` 按首次提交的规则独立校验，不与旧结构比对前缀。重建前把旧条目整版压入 `history`，并在条目上追加 `rebuilds:[{at,reason,from_rev}]`（最多保留20条），界面据此显示「已重建」。条目没有 goal_flow、不是 goal 条目、缺 reason 或新结构非法一律400（`bad_goal_flow` / `bad_reason`），整批不落盘；`submission_id` 幂等与 `base_revision` 冲突规则与其他操作一致。重建后其他条目的 `goal_iteration` 若指向已消失的迭代 ID，整批以 `bad_goal_iteration` 拒绝——须在同一批里改关联或撤回条目。观测本身的删除仍是 `{"id":…,"delete":true}`，它会连同 cursor、条目与历史一起丢弃；只想重做 A→G 时用本操作，不要删观测。

`link_items.remove:true` 按 from/to/type 精确删除关系，并将删除前源条目完整保存至 history；remove 仅接受布尔值，type 缺省 belongs_to，目标关系不存在返回400 no_link。`patch.links` 不支持且明确拒绝。

`POST /api/observations?response=full|refs|changed` 的默认值为 full，兼容旧消费者：full 返回 `{ok,replayed,refs,revision,state}`；refs 返回 `{ok,replayed,refs,revision}`；changed 另加受影响条目的当前 `items`（含 history）与 `cursor`。重放按原批影响 ID 返回现态；旧流水没有影响 ID 时 changed 保守返回全部条目。409 仍附当前 state；新建/删除回执不受模式影响。模式无效返回400 bad_response。

旧观测的 client_ref 从仍保留的 submits 合并，首次成功写入时持久化为 state.refs；重名多义保存为 null，禁止自动选一个。早已从旧流水淘汰的名称无法恢复，须用真实 ID。已成功 submission 仍优先幂等重放，不重新验证、执行旧操作；不得因新增唯一性规则而打破旧批次重试。

`GET /api/ai-guide` 随打包产物提供 [AI_USAGE](AI_USAGE.md) 中每种操作的完整最小 JSON、全部字段取值和目标流示例，离线调用方不必寻找源码契约文件。

#### A→G 连续目标流

仅 goal 条目可携带 `goal_flow={anchor,iterations,events?,tasks?,current?,mode?}`。一个观测最多存在一个未撤回的目标流；已有目标流不能清除或改 kind。anchor 为 `{user_text,understanding,evidence,basis,choices?}`，必填文字是非空最多4000字符；basis 为 inferred / explicit，choices 最多20条非空字符串、每条最多1000字符。

iterations 最多200条，条目为 `{id,actor,before,after,trigger,evidence,basis,parent_ids?,status?,verification?,task_id?,change?}`。id 在流内唯一，1–64字符字母/数字/下划线/连字符，首字符为字母或数字；actor 为 user / ai / user_ai，basis 同 anchor。before/after/trigger 为非空最多4000字符。parent_ids 最多20个唯一的此前迭代 ID，首条默认空数组，后续必须非空。status 默认 active，另有 achieved / unresolved；achieved 必须附 verification。verification 必填 method/text/evidence，method 为 user_acceptance / independent_check，text 非空最多4000字符。所有 evidence 必须含1–50个不重复的有效 req_ ID。

更新必须保留原 anchor、已有 tasks、iterations 及 events 的完整前缀。实质目标变化追加迭代并关联前项；目标不变的达成、未决、重新激活或替代追加 status 事件；外环对自己解释的订正追加 correction 事件，不得伪装为被观察 AI 改目标，也不原位覆盖历史判断。缺省可选字段规范化后比较。非法结构返回 bad_goal_flow，覆盖既有结构返回 goal_flow_frozen，修改已承载目标流的 kind 返回 goal_flow_locked，多个未撤回目标流返回 multiple_goal_flows，均为400且整批不落盘。证据存在性及语义支持仍需外环/用户核对，结构校验不替代验收。

`tasks` 是可选的显式任务数组，最多200项，每项只能含 `{id,title,start_id}`。id 在 tasks 内唯一，id/start_id 沿用 G 的 ID 字符规则；title 非空、最多200字符。start_id 必须指向该任务首个显式归属的 G，不能只声明任务而无对应 G。任务 ID、G ID 和事件 ID 各自独立命名，不自动生成或解析别名；调用方提供稳定 ID。

迭代的 `task_id` 与 `change` 必须同时提供或同时省略，task_id 必须引用 tasks。程序检查显式关系，不从措辞、文件切换或状态机械划分任务。

**两个平面要分清（260909 用户口径）**：G 是对话中的最高目标——用户总体上要达到的结果；T 是 G 的内环，为达成它拆出的交付单元。换一件交付是 `turn`，**不产生新的 G**；只有出现新的结果诉求、整体目标本身改变，才用 `goal`。同一任务内的口径修正是 `refine`，它既不是新 G 也不是新 T。导出页据此分两层：G 段在外，T 区在内，卡片按 `T<第几个任务>·<第几版口径>` 编号，不再把每条迭代都编号成 G。


| change | 严格关系条件 | 阅读含义 |
|---|---|---|
| `initial` | 第一项显式任务的首个 G；父边可接旧无任务字段的 G | 从这里开始记录任务归属；不反向补写旧历史 |
| `refine` | 已开始任务的后续 G；所有父边均指向同一 task_id 的此前 G，可同时引用多个分支 | 同一交付的结果、范围或验收条件发生修正 |
| `turn` | 新任务的首个 G；至少一条父边指向已知其他任务的 G | 同一个整体目标下开始另一项可独立交付的任务，并保留跨任务来路 |
| `goal` | 结构条件与 `turn` 完全相同 | **整体目标本身变了**：用户提出了新的结果诉求。它同时开一个新任务，所以结构规则不变，区别只在语义 |

旧 flow 可继续完全省略 tasks/task_id/change；tasks 与 current 也可分别启用。若在旧 flow 上开始任务归属，保留全部无任务字段的旧 G，追加第一项任务及 initial G；不能改写旧 G 来补标。首次显式归属之后新增的 G 均须提供 task_id/change。任务可并行，也可随后 refine 较早任务；不要求父边是数组中紧邻的 G。turn 不会将旧任务标为达成、替代或结束；这类状态若有证据，仍显式追加 events。

`current` 是可更新的当前说明，只能含 `{goal_ids,understanding,situation,evidence,carryover?,headline?}`。可选 `headline` 是一句口头汇报，非空、**最多120字符**——上限是硬的：程序管不住措辞，但管得住长度，一句话装不下七件事的清单，写的人只能挑最重要的说。省略即没有，页面不会替它从长文里截一句。goal_ids 必须是1–20个不重复的已有 G ID，可引用多个任务的 G；understanding（它对要求的理解）与 situation（它对现状的判断）均非空、最多4000字符；evidence 沿用1–50个有效请求 ID。可选 carryover 是非空、最多4000字符的持续要求与旧任务残件说明。当前说明不从最新 G、status 或完成声明自动生成，也不证明验收。原因假设或现状判断变了但期望结果未变时，可只更新 current，不新增 G。

这两段是**概览，不是工作日志**（260909 实测口径）：每件事一句话讲结果、最多带一个有说服力的数字；「未验收／未确认／未完成／搁置」这类判断必须保留；验证过程与逐项数字写进对应 G 的 trigger、verification 与事件里。粒度判据一句话：同事口头汇报会提这个吗。

`headline` 是这条纪律的落点。反例（260909 实测被判不可读）：「当天依次推进七件事：①切割链默认引擎由 Word COM 换成 Aspose 并用33本文档实测内容等价与速度差；②修复附录显示异常……」——读的人要读完七条才知道现在是什么状况。正例：「切割引擎换成 Aspose 已经跑通，现在在做图片转换失败的可见化；报告核对还没经用户验收。」直接陈述有什么、做到哪、什么没落地，不写实测了什么、设置了什么。

提供 current 会整体替换旧说明，须重新提交必填四字段；此次省略 carryover 会清除旧 carryover，因此仍适用的约束和残件须主动保留。完整 goal_flow 或 delta 都可省略整个 current，保留已保存值；不接受 null 清除。current 的旧版随条目更新进入 history，A、tasks、G、events 仍保持原前缀。

`mode` 是可选的建模模式声明，取 `incremental`（现场逐轮跟随）或 `retrospective`（事后一次性复盘）。缺省表示未声明，旧结构不受影响。它描述这份记录**怎么建的**，不描述被观察的会话；因此不进冻结校验，可以随时改（复盘建完再转现场跟随就改成 incremental），也可以在 delta 里替换。读取方据此判断中间态的可信度：一次性复盘会把「错目标→改目标」压成一句 trigger，声明了模式，读的人才知道该去找 `mistaken` 事件、以及找不到时意味着什么。

**给旧观测后挂目标流**：直接对原来的 goal 条目 `update_item` 挂 `goal_flow` 即可，不要另建条目形成双轨。历史不迁移、不补标——`initial` 仍只用于第一个显式任务的首个 G，旧的无任务前缀保持无任务（260909 实测样本：obs_1805d7a 的 i_8befbc）。

#### A→G 小增量写入

首次用 `add_item.goal_flow` 或 `update_item.patch.goal_flow` 提交完整结构；已有流优先用 `update_item.patch.goal_flow_delta`，它与同一 patch 中的 goal_flow 互斥。delta 只接受 tasks/iterations/events/current/mode 五个可选键，不能是空对象，不能用于 add_item 或初始化，也不接受 anchor。前三项必须是追加数组（允许空数组）；current 与 mode 是整体替换值。delta 不作为条目字段保存，响应仍给出合并后的 goal_flow。

例如已保存第一任务 t1 的 g1 后，结果和验收标准均未改变，只补现状说明：

```json
{"id":"OBSERVATION_ID","submission_id":"current-2","base_revision":1,
 "ops":[{"op":"update_item","id":"goal","patch":{"goal_flow_delta":{
   "current":{"goal_ids":["g1"],"understanding":"检查导出报告及图表是否准确",
     "situation":"已发现数据源差异，报告与图表仍待核对","evidence":["req_b"]}
 }}}]}
```

随后用户要求另一项交付时，同批追加新任务、新 G 及当前说明；示例中的 goal 为已保存的 client_ref，所有请求 ID 须换为实际证据：

```json
{"id":"OBSERVATION_ID","submission_id":"turn-3","base_revision":2,
 "ops":[{"op":"update_item","id":"goal","patch":{"goal_flow_delta":{
   "tasks":[{"id":"t2","title":"操作指南","start_id":"g2"}],
   "iterations":[{"id":"g2","task_id":"t2","change":"turn","actor":"user",
     "parent_ids":["g1"],"before":"核对导出报告与图表","after":"另交付一份可照做的操作指南",
     "trigger":"用户明确提出另一项交付","evidence":["req_c"],"basis":"explicit"}],
   "current":{"goal_ids":["g1","g2"],"understanding":"还需交付可照做的操作指南",
     "situation":"指南尚未编写，报告核对也未验收","carryover":"报告与图表核对仍需继续；两项均用易懂语言说明",
     "evidence":["req_b","req_c"]}
 }}}]}
```

合并后统一校验总量、ID、任务关系和历史前缀；可在一个 delta 中追加 G 与指向它的 event/current，也可在同一批其他条目用 goal_iteration 引用新 G。整个提交复用 revision、submission_id 与原子校验：409 携当前 state，重读合并后再提交；结果不明时原样重放同一 submission_id。换新 submission_id 重复追加同一 G/task/event ID 会被拒绝；非法 delta 连同本批文字、关联、history、cursor 和提交流水全部不写。

#### A→G 事件与工作关联

`events` 为可选数组，最多2000条，只追加不覆盖、不删除。旧结构省略 events 时保持原形状，等价于尚无事件；已有非空 events 在后续完整 goal_flow 更新时不能省略。事件 id 与迭代 id 使用相同字符规则，在 events 内唯一（与迭代 ID 是独立命名空间）；target 必须指向同份 goal_flow 中已有的迭代 ID，仅 correction 另允许 `@anchor`。可同时追加新 G 和指向它的事件，事件数组顺序作为投影先后顺序。

| 事件 | 必填字段与语义 | 最小示例 |
|---|---|---|
| status | id/kind/target/status/text/evidence；status 为 active / achieved / unresolved / superseded / mistaken，achieved 必须另附 verification | `{"id":"e1","kind":"status","target":"g1","status":"unresolved","text":"核验发现仍有遗漏","evidence":["req_a"]}` |
| correction | id/kind/target/text/evidence/basis；basis 为 inferred / explicit，表示外环订正的依据，不改变原 A/G，也不冒充 user/ai 的目标操作 | `{"id":"c1","kind":"correction","target":"@anchor","text":"此前把试用理解成验收，现订正","evidence":["req_b"],"basis":"explicit"}` |

事件 text 为非空最多4000字符；evidence 为1–50个不重复的有效请求 ID；verification 沿用 method/text/evidence 对象及 user_acceptance / independent_check 方法。status 事件可附 verification，achieved 必须有；correction 不接受 status、actor 或 verification。错误结构、未知 target 或重复事件 ID 返回 bad_goal_flow；改写、删除已有事件返回 goal_flow_frozen，均400且整批不落盘。

`superseded`（被后来的目标接替）与 `mistaken`（曾经相信、后来判定方向本身就错了）是两种不同的判定，不可互相替代。两者都只能由 status 事件给出：迭代自身的 `status` 仍只有 active / achieved / unresolved，事后判定不写回当时的记录。标 `mistaken` 的 G 继续留在 iterations 里、继续显示，不允许删除它或只把它压进后一个 G 的 trigger——那正是一次性复盘会丢掉的东西（260909 实测：误做的 compare 档案检查页被验证通过后由用户打断纠正，复盘建模里那个错目标从未存在过）。事件本就必须带 text 与 evidence，所以「怎么发现错的」有地方写且必须挂证据。

当前状态按原迭代 status/verification 起步，再依数组顺序应用 target 匹配的 status 事件，最新状态覆盖旧状态及旧核验，后续 unresolved/active 没有 verification 时不沿用旧达成证据。correction 是可追溯的外环说明，不参与目标状态投影。后续同目标核验不新增 G，已有 goal_iteration 工作归属仍指向同一 G。Python 只读辅助 `observe_goal.project_statuses(flow)` 返回 `{G_ID:{status,verification?,event_id?}}`；事件不会改写持久保存的原 iteration。

当前证据门槛仅验证引用格式及非空数量，不能证明请求存在、属于 scope 或真正支持文字结论。观测状态与原始捕获隔离，历史导出或清理后可能缺原始 HTTP，因此本接口不把缺捕获当作状态写入失败，也不声称 independent_check 枚举等于已核验独立性。消费者应显示引用可核对性，外环应查实引文与结果；仅看到 exit 0 或自报完成不足以填 achieved。

`goal_iteration` 是非 goal 条目可选的显式 G 站点关联；用于 add_item 或 update_item.patch，字符串格式与迭代 id 相同（1–64字符、字母或数字开头，其后可含字母/数字/下划线/连字符）。空串清除关联，省略保留；旧无字段条目不自动归组。所有未撤回条目的非空关联，必须指向本观测唯一未撤回 goal_flow 中已有的 iteration.id；服务端验证整批最终状态，因此可在同批先写工作条目、后新增目标流或迭代。找不到目标、错误类型/格式、goal 条目带非空关联均返回400 bad_goal_iteration，整批不落盘。

撤回目标流时，必须在该批结束前清除、改关联或撤回相关工作项，不能留下活跃悬挂引用。撤回工作项可保留原关联作为历史；重新激活时再次校验。非 goal 条目改 kind 为 goal 时必须清空关联，可在同一 patch 中同时写 kind 与 goal_iteration 空串；原关联和每次变更保留于 history。此关联只表示观察者明确归属，不按时间、标题或数组顺序猜测。

#### 语义图条目与预测边界（兼容旧条目）

以下字段可用于 `add_item`，也可放在 `update_item.patch` 中；省略保持旧值，旧记录无需迁移。

| 字段 | 合同与阅读含义 |
|---|---|
| `title` | 可选短标题，字符串 trim 后最多 200 字符；空串清空。图上优先显示它，详情保留 `text` 全文 |
| `progress` | `planned` / `active` / `blocked` / `done` / `unknown`；这是外环对执行进度的标记，与 `status` 结论可信状态不同。`done` 不证明验收通过 |
| `covers` | 明确归属条目的请求 ID 数组，最多 2000 项，保序去重；空数组清空，超限拒绝而不截断。阶段成员用此字段；`evidence` 只表示论据，不从首末证据猜覆盖范围 |
| `forecast` | 仅 prediction：`{after_rid,horizon_steps,criterion}`，必须且只能含三键。依据截止请求 ID、之后同泳道主请求数窗口（整数 1–5000）、可观察的判定条件（1–2000 字符） |

HTTP 写入还支持 `cover_span:{first_rid,last_rid}`（放在 add_item 或 update_item.patch），与 `covers` 互斥。服务端按当前观测的来源/日期/session/lane和录制顺序展开，含两端且只取两端所在同一泳道的成员，保存为稳定 `covers` 数组；端点缺失、跨泳道、倒序、身份重复或超过2000项均拒绝，错误码 `bad_cover_span`。这让 Agent 为连续阶段只输出两个 ID，不必枚举数百成员，也无需调整图格式。它是调用方显式指定的范围，绝不从 evidence 猜区间；重试已生效批次时无需重新查录制，清理原录制后仍可幂等重放。

`covers` 和 `after_rid` 校验请求 ID 格式，不替调用方证明请求存在或属于该观测范围；界面将找不到的引用显示为不可核对。图的布局由程序负责，Agent 不提供坐标或 Mermaid。推荐关系方向：阶段 `belongs_to` 目标；阶段 `depends_on` 前置阶段；阶段 `produces` 产物；核验项 `supports` / `contradicts` 产物或预测。每种关系只表达调用方写入的判断，不能从排列相邻自动推断因果。

结构化预测一旦有 `forecast`，原 `text`、`forecast` 和 prediction 类型不可改写，撤回后仍冻结；相同值重传允许。展示标题可调整。修正预测需要撤回并新建；后续实际用独立 `check` / `finding` / `deviation` 条目以及支持/反证关系核对。旧预测可首次补结构，但这不证明当时没有看到未来。窗口只帮助判断是否具备核对条件，不自动判断预测命中，不从 `status=supported` 计算准确率。

语义字段非法返回 400，错误码为 `bad_title` / `bad_progress` / `bad_covers` / `bad_forecast`；试图改变封存预测返回 `forecast_locked`。`history` 保留最近 20 个完整旧版（含关系、证据、覆盖与预测结构，不递归保存历史）；关系新增也留旧版。正文仍最多 4000 字符，带 forecast 的超限正文拒绝而非截断。幂等记录保留最近 200 次提交，超出保留窗口后不能依赖同 submission_id 永久去重。

### `GET /api/observations/trace?date=YYYY-MM-DD&source=&lane=&session=` — 阅读投影

只读录制事实，供实时分析的阶段下钻和预测窗口展示使用，不运行推理、不改变原始录制或代理配置。`date` 必须是有效日期，`source`、`lane`、`session` 与录制范围一致；session 和 lane 取交集。

响应包含 `nodes`、`turns`、`lanes`、范围字段、`order:"recording"`、`truncated:false`、`missing` 数量与 `preview_limit`。节点按所选录制顺序返回，`seq` 是此投影从 0 开始的序号，不能传给 `/api/actions?since=`；稳定引用仍用 `id`。节点保留分类器元信息，并增加 `label`、`actions`、`text_preview`、`missing` 和 `has_tool_error`。标签是录制中的操作说明，不是已验证的语义归纳。

每个 action 带 `tool_call_id`、`name`、`label` 和 `result_available`。只将同泳道先前调用与后续请求里的同 ID `tool_result` 配对；找到时含 `result_preview`、`result_truncated`、`result_error`、`result_record_id`。空返回仍是 available；重复调用 ID 显示 `result_ambiguous:true`，不猜归属。预览最多 320 字符，完整原文按需读 `/api/captures/<id>?date=…&source=…`。缺失记录明确报告，不能把工具返回成功当成用户目标实现。

进程缓存只保留少量范围的精简投影，轮询读新追加的记录；覆盖、删除或压实导致索引前缀变化时重建。没有语义条目时仍能显示录制轮次，但不能把轮次称为任务阶段。

### `POST /api/captures/clear` — 清除录制

**请求**：`{ "date": "2026-07-12", "mode": "purge"|"archive", "source"?: "标签", "label"?: "机器名" }`。`date` 缺省=今天；`mode` 缺省=`purge`。`date` 经 `YYYY-MM-DD` 格式 + 语义校验（防路径穿越）。

- `mode=purge`：直接删这一天（jsonl 主文件+索引，或整个 `<date>.pack/` 目录）
- `mode=archive`：先归档成 `archives/<date>[.<label>].<HHMMSS>.ccwa`，再删原录制

**响应**：
```json
// purge
{ "ok": true, "removed": 42 }
// archive
{ "ok": true, "removed": 42, "archive": { "path": "~/.cc-wire-analyzer/archives/2026-07-12.193021.ccwa", "size": 12345, "count": 42 } }
// 失败（HTTP 500）
{ "ok": false, "error_code": "bad_date|not_found|delete_failed|archive_failed|internal", "error": "…" }
```

`removed` = 删除的记录条数。

**260825 破坏性变更**：archive 的产物从 `<date>.<HHMMSS>.jsonl.zip` 换成 `.ccwa`，响应里的
`archive.compressed` 字段随之移除（换成 `count`）。旧的 zip 归档不会被动，仍会出现在
`/api/sources` 的 `archives` 列表里并标 `legacy: true`，但**本版本不能导入它们**——
它们就是一个装着 jsonl 的 zip，解开即可直接用。

---

## 3. 存储形态：压实 / 归档 / 导入

一天有两种形态：`captures/<date>.jsonl`（今天，格式未变）与 `captures/<date>.pack/`（过去某天，
已压实）。**所有读取端点对两种形态行为一致**——同一天压实前后 `/api/captures`、`/api/dag`、
`/api/captures/<id>`、`/api/grep` 的响应逐字节相同；`/api/stats` 只有 `file_size` / `packed` /
`raw_bytes` 三个字段会变，因为它们的语义就是"现在占多少"。

压实做的是内容寻址去重 + 逐块 zstd，**逐字节可还原**（压实前全量比对，通过才删原文件）。
为什么值得做、实测省下多少、随机读多快，见 [开发约定.md](../development/开发约定.md) 的「为什么要压实
（数字先于设计）」——那一节是这些数字的主页，别在这里抄第二份。

### `POST /api/captures/compact` — 压实（原地缩小，不删数据）

**请求**：`{ "date"?: "2026-08-24", "source"?: "标签", "older_than"?: 7 }`。
不给 `date` 则压实全部「过去的、还没压实的」天；`older_than` 再按天数过滤。
**今天永远不压**（`append` 正往里写，代理透明性优先于省空间）。

**响应**：
```json
{ "ok": true, "saved_bytes": 485532286,
  "compacted": [{ "date": "2026-08-09", "count": 855, "raw_bytes": 500284782,
                  "packed_bytes": 14752496, "saved_bytes": 485532286, "ratio": 33.9,
                  "blob_count": 2227, "elapsed_ms": 31471 }],
  "failed": [{ "date": "…", "error_code": "is_today|already_packed|not_found|verify_failed", "error": "…" }] }
```

失败是**逐天**的：一天压不了不影响其他天。`verify_failed` 表示还原出来与原文件对不上——
这种情况原录制**一个字节都没被删**，pack 半成品已清掉。

### `POST /api/captures/uncompact` — 还原回 jsonl

**请求**：`{ "date": "2026-08-24", "source"?: "标签" }`。
**响应**：`{ "ok": true, "date": …, "count": 855, "bytes": 500284782 }`。
还原后按 manifest 里记的原文件哈希复核，对不上就删掉半成品并报 `verify_failed`。

### `POST /api/captures/archive` — 归档成可搬运的单文件

**请求**：`{ "date": "2026-08-24", "source"?: "标签", "label"?: "机器名", "clear"?: false }`。
`clear=true` 才删原录制（默认保留——跨机排查时源机器通常还要继续用自己的录制）。

**响应**：`{ "ok": true, "path": "…/archives/2026-08-24.laptop.193021.ccwa", "size": 14753387, "count": 855, "removed": 0, "kept": true }`

### `POST /api/captures/import` — 导入别的机器的归档

**请求**：`{ "file": "C:/…/2026-08-24.laptop.193021.ccwa", "label"?: "laptop" }`。
标签缺省取归档里记的 `label`。落到 `sources/<标签>/<date>.pack/`。

**响应**：`{ "ok": true, "label": "laptop", "date": "2026-08-24", "count": 855, "bytes": 14752496,
"from": "0.4.16", "host": "DESKTOP-A1B2C3", "foreign": true }`
失败码：`not_found` / `bad_archive` / `schema_mismatch` / `already_imported` / `bad_label`。

`host` = 归档产出机器名（归档 manifest 里记的，只有 hostname、不含用户名），`from` = 产出它的
本工具版本，`foreign` = 与本机名不同（即"这是另一台机器的录制"）。老归档没有这两个字段时
`host` 为空、`foreign` 为 `false`——**空不等于本机**，只等于"答不上来"。

**为什么必须进独立命名空间**：两台机器同一天都在录，日期一定撞车。混进 `captures/` 的后果
不是报错，而是更糟的东西——把别的机器的证据当本机事实读，排查会直接跑偏。

### `GET /api/sources` — 已导入的来源 + 本机归档清单

```json
{ "ok": true, "host": "本机名",
  "sources": [{ "label": "laptop", "dates": ["2026-08-24"], "days": 1, "count": 855, "bytes": 14752496,
                "host": "DESKTOP-A1B2C3", "foreign": true, "from": "0.4.16",
                "archived_at": "2026-08-25T19:30:21" }],
  "archives": [{ "name": "2026-08-24.laptop.193021.ccwa", "path": "…", "size": 14753387,
                 "date": "2026-08-24", "count": 855, "label": "laptop", "raw_bytes": 500284782,
                 "archived_at": "2026-08-25T19:30:21",
                 "host": "DESKTOP-A1B2C3", "from": "0.4.16", "foreign": true }] }
```

顶层 `host` 是**本机**名，条目里的 `host` 是那份录制的产出机器，`foreign` 就是两者不同。
标签是人起的（可以起错、可以撞名），机器名是归档时自动写进去的——判断"这是不是另一台机器
的数据"看 `foreign`，别看标签。老归档没有 `host`，那时显示为空：**空 = 答不上来，不等于本机。**

坏归档不会从列表里消失，而是带 `error` 字段列出来。旧的 zip 归档带 `legacy: true`。

### `POST /api/sources/delete` — 删掉一个导入来源

**请求**：`{ "label": "laptop" }` → `{ "ok": true, "label": "laptop", "days": 1 }`。
外来录制不参与保留天数，只能显式删。

### 读取端点的 `source` 参数

`/api/captures`、`/api/captures/<id>`、`/api/dag`、`/api/actions`、`/api/grep`、`/api/stats`、`/api/unknowns`、
`/api/diagnose/errors` 都接受 `source=<标签>`：空/不给 = 本机录制，给了 = 看那个导入来源。
CLI 对应 `--source`。

---

## 4. 配置

### `GET /api/config`

```json
{
  "ui_lang": "zh",
  "ui_scale": 100,
  "auto_start_proxy": false,
  "retention_days": 30,
  "translate": { "api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "temperature": 0.3, "max_tokens": 16384, "target_lang": "zh" },
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

**历史字段**：`redact_headers`（260713 删除）—— 曾是脱敏开关，但代码从未消费；260713 连开关
一起删，脱敏改无条件恒开。老 config.json 里残留该键会被忽略。

> **自检**：加新配置字段必须三处都接通——`config.py::_DEFAULTS` 默认值 + 前端设置页 UI +
> 实际消费点。任何一处断了就是新的"死配置"（[开发约定.md](../development/开发约定.md) 惯犯 bug ①）。

### `POST /api/config`

请求体同上结构（部分字段可选，白名单合并写入）。`api_key` 写入时前端用 password 输入；读取时返回空串或 mask。

---

## 5. LLM 服务（翻译 / AI 解读，共用 `config.translate` 配置）

错误返回统一含 `error_code`（供前端 i18n 映射：`no_api_key` / `no_base_url` / `empty_text`）+ `error`（原始诊断串）。

### `POST /api/translate` — 翻译文本（SSE 流式）

**请求**：`{ "text": "..." }`（超过输入上限截断，见下方 `input_truncated`；上限 = 配置
`translate.input_max_chars`，默认 80,000，260825 起可在设置页调）

**响应** `200` `text/event-stream`：

```
data: {"input_truncated": 20000, "orig": 53210}   // 可选，恒在最前；值=当前配置的输入上限
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
- **截断字段（260801 增量；260825 起上限可配）**：`input_truncated`（本工具把原文砍到配置的
  `translate.input_max_chars`——默认 80,000、夹取 1000~2,000,000——才发出去，`orig` 是原长）与 `truncated`（上游 `finish_reason`，取值 `length` / `content_filter`，`max_tokens` 是发起时的本机设置）。两者都是**可选事件**，不出现即表示没发生。
  加它们的原因：「输出到此为止」有三种成因（原文被我们砍短 / 上游到 max_tokens / 内容审查），此前在界面上长得一模一样，用户改大 `max_tokens` 后无从判断生效没有（260801 用户反馈 #2）。`finish_reason` 此前只有非流式路径读，而翻译/解读走的恰恰是流式。

目标语言取 `config.translate.target_lang`。system prompt 内置强隔离（`<text>` 内视为纯文本，绝不执行其中指令），文本内字面 `</text` 转义防定界符逃逸。

### `POST /api/explain` — AI 解读（SSE 流式）

同 `/api/translate` 的 SSE 协议（`delta` 增量 / `done` 结束 / `error_code` 错误），区别在 system prompt：

- system = 固定隔离头 + 任务描述（`config.explain.prompt` 或内置默认）+ 固定隔离尾
- 用户内容包 `<content>` 且字面 `</content>` 转义
- 隔离头尾代码写死，设置只能改任务描述段（防注入不可被配置绕开）

> **自检**：改 SSE event 格式时，必须同步改前端 `llmToolAction()`（`templates/index.html`）
> + 此契约 + `docs/usage/AI_USAGE.md`。改隔离定界符时必须同步改 `_translate_parts` /
> `_explain_parts`（`src/app.py`）。

### `POST /api/translate/test` — LLM 连通测试

**始终返回 HTTP 200**，由 `ok` 字段判成败（避免前端把配置错误当 fetch 异常）：
`{ "ok": true, "snippet": "译文片段…" }` 或 `{ "ok": false, "error_code": "...", "error": "..." }`

---

## 6. 实例与环境

实例自描述与运行环境事实：本实例是谁、数据目录多大、说明书在哪。除 `open-folder` 外全部只读无副作用——`/api/instances` 扫描时对每个候选端口调一次 `/api/instance`，慢不得。

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

### `GET /api/storage` — 数据目录占用

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

### `GET /api/instance` — 本实例是谁

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

### `GET /api/instances` — 本机在跑的所有实例

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

**为什么不读 `port.txt` / `serve.pid`**：那两个文件单份、后写覆盖、无实例归属、退出不清理
（260809 实测 `serve.pid` 停在六天前一个已退出的 PID）。本端点因此**不依赖任何持久化状态**，
也就不可能显示过期信息。写入侧的契约要不要改属 0.5.x，与本端点无关。

### `GET /api/ai-guide` — 自描述说明书

**不返回 JSON**：`Content-Type: text/markdown; charset=utf-8`，body 是 Markdown 原文。

结构固定为两段：

1. **本机运行期事实**（服务端现场生成）：`version` / 本实例实际监听地址 / 代理是否处于录制态 /
   数据目录 / 录制目录 / 被接管的 settings.json / 日志路径，全部是**绝对路径**。
   动机：文档正文写的是 `~/.cc-wire-analyzer/` 与"端口从 5051 起挑"，而调用方需要的是这台机器上
   的确切值。
2. **完整用法说明正文**：`docs/usage/AI_USAGE.md`，随产物打包（`build.spec` / `build-mac.spec` 的
   `datas`），冻结态从 `_MEIPASS/docs/` 读、源码模式从仓库 `docs/` 读。

**永不 500、永不空**：两条路径都取不到文件时回落到内置的最小速查（端点表 + 三条铁律），并在
`run.log` 记一条 warning。同一份正文也由 `cc-wire-analyzer --help` 打印。

### `POST /api/open-folder`

用系统文件管理器打开目录（备份 / 存档等）。**仅允许数据目录内的路径**，防任意打开。

请求 `{ "path": "~/.cc-wire-analyzer/backups" }` → `{ "ok": true }` 或 `{ "ok": false, "error": "路径不在数据目录内" }`

---

## 7. 就地更新

**"点一下就换好"，不是"自动升级"**：没有定时检查、没有静默安装，每个端点都对应界面上的
一次点击。安全边界见 [开发约定.md](../development/开发约定.md) 不变量 10（来源硬编码 / 逐跳 host 白名单 /
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

## 8. 配置体检

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

## 9. 失败聚合

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

### `GET /api/diagnose/trends?span=7&model=&kind=&limit=20` — 跨天失败趋势

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

## 10. 检索与统计

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

## 11. 盲区雷达

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
| `other_kind_samples` | 固化 `quota_probe`/`hook_eval`/`notify_eval` 后仍落 `other` 的真未知（理想为空）| — |
| `known` | 当前已知集合基准（真源 `classifier.KNOWN_*` + `KNOWN_BETAS`）| 让 AI 判断「什么算未知」 |

**`KNOWN_BETAS` 的真源在 `classifier.py`**，前端由 `render_template(known_betas=…)` 注入消费——
260802 之前它只硬编码在 `index.html`，于是唯一会问"有没有新 beta"的消费者（AI 走本端点）拿不到，
只能退而按频次猜。

> **自检**：加新 kind 或扩充 `KNOWN_*` / `KNOWN_BETAS` 必须同步改 `classifier.py` + 此契约 +
> 架构总览 kind 列举 + 界面导览/报文解读的 kind 表 + `IDX_SCHEMA` bump + `cli_selftest.py`
> 的 `[1.5] 盲区雷达` 段。

---

## 12. 快照：提示词/录制的备份、精确对比、思考链

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
{"kind": "capture", "record_id": "req_cc08fa7", "date": "2026-08-26", "source": "另一台机的标签"}
```

`source`（260826 补）：备份**导入来源**里的录制必须带上，否则在本机命名空间里找
`record_id`，得到 `not_found` 404——读取面 v0.4.15 就接了 `source`，这条备份链路
当天漏了，用户真机在导入来源下右键备份时首撞。

`where` 三形态（**提示词不只在 `system` 里**——实测一条主线请求的指令来源有五处，
见 [同类工具构建手册.md](../guides/同类工具构建手册.md)）：

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

### `POST /api/snapshots/export` — 快照便携包

body `{sids: ["snap_…"], note?}` → 在 `archives/` 里产出一个 `.ccwa`，返回 manifest：

```json
{
  "ok": true, "kind": "snapshots", "snap_schema": 1, "count": 2,
  "items": [{"sid": "snap_…", "kind": "capture", "label": "…", "created": "…",
             "has_analysis": true, "has_chat": false, "bytes": 2049181}],
  "host": "…", "tool_version": "0.4.17", "exported_at": "2026-08-27T15:34:58",
  "path": "…/archives/snapshots-20260827-153458.ccwa", "size": 891369
}
```

**搬的不是快照本身，是它旁边那份归纳**：一份 97KB 的 `analysis.json` 实测花了 27 批、
26 分钟。没有这条通道，换一台机器（或换一个人）就只能重跑一遍，重新花一次钱、重新等半小时。

- **与录制归档同后缀 `.ccwa`，靠 manifest 里的 `kind` 区分**（`snapshots` / `captures`）。
  老的录制归档没有 `kind` 字段，按 `captures` 处理。用户那边只有一个"导入"，
  文件是什么由工具自己看出来。
- **签名与归档同源**：`host` 只取机器名不取用户名（包会被拷来拷去，机器名足以分辨两台机器，
  泄露面小得多），`tool_version` 取真实版本。
- 包内布局 `snapshots/<id>.json` + `.analysis.json` + `.chat.jsonl`（后两份可缺）。
- 空选择 → `no_snapshots`，**不产出一个空包**。

### `POST /api/snapshots/import` — 导入快照便携包

body `{file: "<绝对路径>"}` → `{ok, imported, renamed, skipped, items, manifest, host, foreign}`。

⚠️ **同 sid 不覆盖**：撞了就换一个新 sid 落地，`renamed: [{from, to}]` 如实报回来。
盖掉本机同名快照 = 拿别人的证据顶替自己的，正是 `sources/` 独立命名空间要防的那件事。
落地后信封里多一个 `imported_from {host, tool_version, sid, at}`，界面据此标出"这不是本机的"。

- 归纳里的 `sid` 会跟着改写成落地后的 sid——不改就与快照对不上。
- **子代理线在对面机器上捞不到**（`_subagent_lanes` 要回当日录制里找，而那台机器没有那天的录制）。
  所以包里已生成的子代理简报与线级结论是对面唯一还能读到的部分，它们随 `analysis.json` 一起走。
- 传进来的是录制归档 → `wrong_kind`；不是本工具的包 → `bad_archive`；版本不认 → `schema_mismatch`。

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

**`availability` 分三档，读不到思考时也要给得出东西**：

```json
{"tier": "B", "reason_code": "disabled",
 "reason": "本次请求显式关闭了思考（thinking.type=disabled）",
 "steps": 12, "steps_with_thinking": 0, "steps_with_plaintext": 0, "thinking_chars": 0,
 "thinking_param": "disabled", "model": "claude-sonnet-5"}
```

- `A` 有可读思考链 → 三层全功能
- `B` 没有思考块 → 附 `behavior` **行为链**（工具序列 + 反复证据：连续同工具、反复读同一目标、
  报错重试），并说出具体原因。实测 claude-sonnet-5 档 23/23 全部 `thinking=disabled`
- `C` 思考块在、内容读不到 → 同样附 `behavior`，不试图解析。两种原因码：`redacted`
  （`redacted_thinking`，上游加密）、`signature_only`（块带 `signature` 但明文没回传，
  260904 实测 claude-opus-5 有三条录制整条如此）

**判档只认明文**：`steps_with_thinking` 数的是**块存在**，`steps_with_plaintext` 与
`thinking_chars` 才是内容量——两者可以是 86 与 0。别拿块数判"有没有思考可读"
（这正是 260901 那个把空块判成 A 档的缺陷）。A 档若夹着空块，另给 `partial_empty: true`；
夹着加密块给 `partial_redacted: true`——"它没考虑过 X"可能只是那几步读不到。

判档在**步**这一级做，不在模型级：`adaptive` 是主流形态，同一模型内部也会有的步不思考。

### `GET|POST /api/snapshots/<id>/analysis` — 骨架的 AI 语义层（仅录制快照）

`GET` 读已有（**不调模型**，`{ok, exists, data}`）；`POST` 跑一次（重新分析就是再 POST 一次）。
存成 `<id>.analysis.json`——不进快照信封：信封是不可改的，这份是可重算的派生物。

一次 POST 做三件事，落在同一份文件里：轮级归纳（`turns` / `summary`）、主线**步级简报**
（`steps`：`{step, title, detail}`，`title` 一句话、`detail` 是为什么/发现/放弃）、以及各条
**子代理线的步级简报**（`sub`，按 `lane_id` 分组；账目在 `sub_meta`）。

- 语义层只挂在**程序抽出来的真实步号**上：越界步号一律剔除并记进 `dropped_steps`——
  没有这条，"AI 归纳挂在程序事实上"就只是一句说辞。
- 单批失败不连坐：`steps_brief_meta.failed_batches` / `sub_meta.failed_batches` 如实自陈，
  界面把没归纳到的步退回机械行。
- 老格式兼容：早期缓存与自定义提示词产出的单段 `brief` 仍可渲染（落进 `detail`）。
- 任务段可在设置页覆盖（`analysis.turns_prompt` / `analysis.steps_prompt`），
  **防注入定界与规则永远内置**——能调叙事风格，不能拆隔离墙。
- 失败码：`not_capture` / `no_steps` / `bad_json`（模型没给出可解析 JSON，如实说，不留空面板）。

### `GET /api/snapshots/<id>/analysis/progress` — 正在跑的那次归纳跑到第几批了

一次归纳现在可能是几十个批次（主线十来批 + 每条子代理线各自的批，实测 27 批 / 26 分钟）。
`{"ok": true, "running": true, "phase": "turns|steps|sub", "batch": 3, "batches": 9,
"lane": 2, "lanes": 6}`；没在跑就是 `{"ok": true, "running": false}`。

**只存在内存里**：重启即失，多实例互不可见。它是一次前台点击的伴随信息，不是需要持久化的
事实。归纳无论成败都会清掉——一条永远停在"12/27 批"的进度，比没有进度更像还在跑。

### `GET /api/snapshots/<id>/subagents[?lane=&step=]` — 这条录制派出去的子代理线（仅录制快照）

快照的 payload 是**一条请求**（主线的完整历史）。子代理的过程不在里面：主线 `messages` 里
只有一次 `tool_use(Task)` 和最后那份报告，它自己想了什么、翻了哪些文件在**另外的请求**里。
这个端点把那些请求接回来，一条线一份 L0 骨架，并给出它挂在主线**哪一步**。

关联键全是 DAG 早就在用的，不新发明判据：泳道靠 `X-Claude-Code-Agent-Id`（老录制回落派生
prompt 对齐），父子靠 `trigger` 边（派生 prompt 前 300 字 ⊂ 子代理剥掉 reminder 后的首条
user），挂到哪一步则是同一条判据、只是拿快照自己那一步的 Task prompt 去比。子代理再派生
子代理沿边递归（最深 3 层，最多 12 条线，超了 `truncated: true`）。

```json
{ "ok": true, "available": true, "source": "", "task_calls": 6, "truncated": false,
  "agents": [{ "lane_id": "agent-guide-builder@session-314c8b37", "agent_id": "…",
               "parent_lane": "", "depth": 1, "trigger_step": 18,
               "label": "派生 prompt 前 120 字", "record_id": "req_…", "requests": 46,
               "first_ts": "…", "availability": { "tier": "A" },
               "steps": [ … L0 骨架行 … ], "steps_total": 44, "omitted_steps": 0 }] }
```

- `parent_lane` 为空串 = 挂在主线（快照这条）；非空 = 挂在另一条子代理线上（嵌套派生）。
- `trigger_step` 为 `null` = 这条线**挂不到具体步骤**（派生 prompt 对不上：跨天截断、或派生方
  那条请求没被录到）。**照样返回**，界面会单列并说明——悄悄丢掉等于宣称"它没派过子代理"。
- `task_calls` 是主线自己派发过几次 Task。它与 `agents` 数对不上，就是"有派生没录到"的直接证据。
- `available: false` + `reason_code`（`recording_gone` / `not_in_dag` / `no_record_id`）：
  快照是自包含的，子代理线不是——它要回当日录制里捞。**录制被清理或归档走了要明说**，
  不能渲染成"这条会话没有子代理"。
- `lane=<lane_id>&step=N`：那条线单步的思考原文，与主线 `thinking?level=2` 同义（同样的
  `level2` 产物），只是换了条记录。线不在了返回 404 `lane_not_found`。

### `GET|POST /api/snapshots/<id>/trajectory` — 轨迹八视图（仅录制快照）

程序层即时算（~20s/条录制），语义层有缓存就带上、没有就机械兜底并标 `semantic:"degraded"`。

- 不带参数 → `{ok, exists, semantic_exists, data}`。`data` 是八视图 payload：
  节点 / 动作 / 物料 / 血统 / 验证等级 / 阀门 / 未验债 / 成本 / 子代理线 / 必要闭包 / 阶段。
- `?format=html` → **完整的八视图单文件页**（payload 内嵌，零外部依赖，单独打开也能用）。
  另认两个外观参数：
  - `theme=dark|classic|light` —— 不给则读 `ccwa_ui_theme` cookie，跟随主界面；
  - `embed=1` —— 嵌入模式：背景透明、去掉自己的顶栏与滚动条，高度与可视区通过
    `postMessage` 与父页协商（父页那半边见 `index.html` 的 `anTrajViewport()`）。
    页面同时暴露 `window.ccwaTrajTheme(t)` 供父页即时换肤——**不能用 reload 换肤**，
    payload 内嵌在页面里，reload 等于让服务端重算一遍。

- `POST` → **跑语义层**（`?mode=resume|redo`）：一条可续跑的三段流水线——阶段切分
  （程序给候选边界、模型定名）→ 状态快照四格（每阶段一次，并发）→ 步级简述（分批并发）。
  进度走既有的 `analysis/progress` 通道，phase 前缀 `traj_`。跑完丢掉该 sid 的 HTML 缓存。

地基是**全部主线请求的 blocks 并集**（`tool_use` id / `tool_result` id / 文本 md5 三键去重），
不是单条最长请求——autocompact 剪掉的前半段只有并集能捞回来。当日数据已归档成 `.ccwa` 时
如实回 `archived_or_missing`，而不是渲染半截 run。

### `GET /api/snapshots/<id>/semantic` — 八视图语义层的存在性探测（仅录制快照）

只回 `{ok, exists}`，**不调模型、不拉 payload**（前端状态条用）。
跑语义层是 `POST …/trajectory` 那条——260904 校对发现这里此前写成 `GET|POST /semantic`，
描述的 POST 其实不在这个路径上，是端点标题的机械事实第一次被对账查出来。

结果存 `<id>.semantic.json`（与 `analysis.json` 同待遇的可重算派生物：随快照删除清理、
计入 `size_of`、跟着便携包搬）。**事实四格不落盘**：`artifacts/pending/errors/constraints`
在 compute 时由 `_attach_phase_facts()` 现算盖掉——模型改不了事实。

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

上下文**不落盘**：快照不可变，重算是确定的；落盘则每条 `chat.jsonl` 都被整段上下文撑爆，
而外部 agent 读 `/chat` 时想看的是对话本身。B 档快照的 system 里**写死禁止推测思考内容**
（附具体原因）——让模型自己判断有没有思考链不可靠，我们已经知道答案就该写死。

落盘时机是**回答产出之后**：没配 Key 这类连上游都没到的失败，不该在对话记录里留下一串
没人回答过的提问。中途出错时半截回答照样落盘，但会附上中断原因——半截存成完整，
下一轮模型会把它当作已说完的话接着推。

预算：`CHAT_CONTEXT_MAX` 保留 20000 作为异常回退；正常新配置默认 80000、真值 = 配置 `translate.chat_context_max_chars`
（其中 `CHAT_SOURCES_MAX=4000` 给多源清单，随上限联动）/
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

## 13. API 浏览面：人类可读渲染

本工具是双模式的——**人看 GUI（`/`），AI 走 `/api/*`**。这一节是给这两条通道之间开的一扇窗：
让人能在浏览器里亲眼核对 AI 那一侧拿到的是什么。原本返回 HTML 的只有 `/`，`/api/*` 一律 JSON、
`/api/ai-guide` 是 markdown 原文，于是「我把『复制给 AI 的一句话』发出去之后，agent 究竟读到了
什么」对用户全黑。

> ⚠️ **契约上最重要的一句：不带 `?format=html` 时，`/api/*` 的响应逐字节不变。**
> 这一节不改任何既有端点的出参。AI 消费方可以完全忽略本节的存在。

### `GET /view` — 浏览面首页

列出全部可 GET 的 `/api/*` 端点（**从 `app.url_map` 现取，不是硬编码清单**），分组、每条
一句话说明、每条一个可点链接。返回 `text/html`。

需要参数的端点（`/api/captures/<rid>`、`/api/snapshots/<id>/*`，以及靠 `?a=&b=` 传两个 sid 的
`/api/snapshots/diff`，共 10 条）给一行**可编辑的完整 URL**，预填的样例由后端从**本机真实数据**
里挑（`_view_sample_ids`：最近有数据那天的第一条 rid；快照优先挑**已经归纳过的录制快照**——
`/analysis`、`/subagents` 落在别的快照上打开是空的，而空页会被读成"端点坏了"）。挑不到才退回
参考写法，并在旁边如实标成「参考写法」（清单里的 `example_real=false`）——不标就是在骗人照抄一个
跑不通的地址。`/api/captures/<rid>` 的样例带 `date=`（历史日期不带 date 查不到），diff 的样例带齐
`a`/`b`：**样例的全部价值在于照抄就能跑**，少一个参数就退化成了另一种占位符。

`/api/captures/stream`（SSE 长连接）与 `/api/update/check`（会联网）列出但**有意不给链接**，
并在行内写明原因——藏起来就等于浏览面自己有盲区。反过来，`diff` 此前是有直链的，点下去必然
报错；**给一个注定失败的入口比留白更糟**，所以它改走输入框那条路。

页面外观跟随主界面的三套（`ccwa_ui_theme`，cookie + localStorage），顶栏那个三色开关写的是
同一对键——同一个设置的第二个入口，不是第二个真相源。

### `?format=html` — 任意 `/api/*` GET 端点的渲染视图

在任何 GET 端点后加 `format=html`，返回渲染后的 `text/html` 而不是 JSON：

```
GET /api/captures?date=2026-08-15&limit=20&format=html   → 表格
GET /api/captures/<id>?date=2026-08-15&format=html       → 折叠树
GET /api/ai-guide?format=html                            → 排好版的说明书
```

| 行为 | 说明 |
|---|---|
| 生效条件 | `GET` + 路径以 `/api/` 开头 + 响应 `content-type` 是 `application/json` 或 `text/markdown` |
| 不生效 | POST 等非 GET、代理 catch-all 路径、流式响应（SSE）、其他 content-type —— 一律原样返回 |
| 状态码 | 沿用原响应（404 也会被渲染出来看，这是有意的） |
| 数据保真 | 页面内以 `<script id="payload" type="application/json">` 内嵌**原样字节**，`<` 转义成 `<`（等价变换）。页面顶部同时给出实际 URL、HTTP 状态码、响应字节数与「原始 JSON」链接 |
| 大响应 | 超过 4 MB 不渲染，页面写明字节数与上限并给出原始 JSON 入口。**不截半份给你看** |

数组元素同构且并集列数 ≤ 40 时渲染成可横向滚动的表格；超过则退回列表并在页面上写明原因
（**任何情况下都不砍列**）。长字符串折叠，但一律带「展开全文（N 字符）」。

不变量与理由见 [开发约定.md](../development/开发约定.md) 第一节第 11 条；自测 `tests/view_selftest.py`。

---

## 14. 约定

- **headers_safe**：所有 headers 字段经脱敏，`authorization` / `x-api-key` / `anthropic-auth-token` 显示 `<redacted>`，列表/详情都不返回真实 token。**脱敏无条件生效，没有开关**（曾有个 `redact_headers` 配置项，但从未接线；260713 连开关一起删掉 —— 提供"明文存 key"的选项本身就是危险，何况录制现在可被 AI 经 CLI 读取）。
- **时间格式**：ISO 8601 带毫秒，本地时区（`2026-07-05T22:43:12.345`）。
- **usage 字段名双轨**（重要，易踩坑）：
  - **录制文件 `{date}.jsonl` 与 `/api/captures/<id>` 完整 record**：写 Anthropic 全名（`input_tokens` / `cache_read_input_tokens` 等）—— `proxy._parse_sse` 直写上游返回
  - **`/api/captures` 列表、`/api/dag` 节点、`/api/captures/stream` SSE 摘要**：归一后短名（`input` / `output` / `cache_read` / `cache_creation`）—— `classifier.index_record` 经 `usage_norm`（单一真源）转换
  - 前端 `templates/index.html` 自带 fallback（`ur.cache_read_input_tokens ?? ur.cache_read`）兼容两种形状，但**契约规定的列表/DAG 出参是短名**
- **lane_id 命名规则**：
  - 主线泳道：`s-<md5(session_id)[:8]>`（session_id 来自 `X-Claude-Code-Session-Id` 头，回落 `metadata.user_id` 内 session_id）
  - 子代理泳道：`agent-<md5(派生者id + 派生prompt前200字)[:8]>`（对齐命中时）或 `agent-<agent_fp>`（对齐未命中回落，agent_fp = system block[2] md5 短码）
  - 辅助调用：`aux`（所有会话的 title/security/count_tokens/compact/quota_probe/hook_eval/notify_eval/self_prompt/other 合一列）
- **kind 枚举**（真源 `src/classifier.py` 的 `KIND_ORDER`）：`main` / `subagent` / `title` / `compact` / `security` / `count_tokens` / `quota_probe` / `hook_eval` / `notify_eval` / `self_prompt` / `other`。`quota_probe`（CC 配额嗅探：`user="quota"`+maxtok=1）与 `hook_eval`（StopConditions hook 评估）260802 前落 `other`、`notify_eval`（走开通知的状态判定：无工具 + system 含 `whether to notify the user`）260902 前落 `other`，现均固化；`self_prompt`（CC 自己发起的一整轮：建议补全 / 离开回顾 / 内部检索派发）260902 前判 `main`，现按 CC 自己的记录改判辅助（那三族在 jsonl 里没有 `promptId`）；其余未知形状仍落 `other`。完整语义见 [架构总览.md](../development/架构总览.md) "2.1 分类与 DAG"。
- **err_kind 枚举**（真源 `src/proxy.py` 错误分类段）：`connect` / `timeout` / `http_error` / `upstream_4xx` / `upstream_5xx` / `stream_error`（HTTP 200 但 SSE 流内报错，260731 补）。
- **harness 声明面字段**（索引项，`IDX_SCHEMA=6` 起）：`beta`（`anthropic-beta` 拆成的特性数组——CC 声明启用了哪些协议扩展）/ `agent_id`（`x-claude-code-agent-id`，CC 给的子代理实例 ID）/ `ctx_mgmt` / `diagnostics` / `stop_seqs_n` / `thinking_budget`。这些是**发现录制盲区的信号源**，不是判别位——子代理判别仍以 system block[0] 计费头的 `cc_is_subagent` 为准（见 [开发约定.md](../development/开发约定.md) 子代理判别定案）。
- **大字段**：`request.body` / `response.content_blocks` 可能很大（MB 级），详情接口一次性返回；前端用虚拟滚动/折叠渲染。
- **错误透传**：上游 4xx/5xx 也要录（response 存原文 snippet），原样返回给 CC，不破坏 CC 错误处理。
- **路径前缀**：UI 所有路由必须 `/api/` 开头，否则会被代理 catch-all 当成上游流量转发。
  （例外只有页面：`/`、`/favicon.ico`、`/view`。加页面路由等于在代理面上多占一个路径，
  Anthropic 的 API 都在 `/v1/*` 下，目前不冲突，但**新增页面路由前先确认不撞上游路径**。）
- **`format=html` 是保留 query 参数**：任何 GET 端点都不该把 `format` 用作业务参数，否则会
  与浏览面的渲染开关撞车。现有端点均未使用。

**本文档维护**：按 [开发约定第十一节](../development/开发约定.md#十一改动流程issue-先行) 的 SSOT 原则——枚举真源在各模块
docstring，本契约引用而不重复定义。改字段集必须 bump `IDX_SCHEMA` 并同步此契约 + AI_USAGE
+ 界面导览 + 架构总览四份文档的相关段。
