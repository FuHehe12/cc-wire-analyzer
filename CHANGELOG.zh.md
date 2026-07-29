# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步，英文版为源。

## 项目速览

> 定位 / 当前状态 / 下一步——AI 接手快照。仅作导航；属规则/不变量的关键判断见本地 CLAUDE.md（开发约定）。详细变更历史见下方各段。下方条目里的 issue 路径是本地维护记录（gitignored，不在本仓库）。

- **定位**：本地 MITM 代理桌面应用，透明录制 Claude Code ↔ 上游端点的全部 HTTP 流量，填补 jsonl 日志与 OTLP 遥测看不到的链路级维度。双模式：GUI 给人看，`serve` 子命令暴露 headless HTTP API，让 AI agent 自己驱动排查。
- **当前状态**：**v0.4.0 已发布**（2026-07-28）。三件大事一同落地：**泳道判别定案**（系统头计费位 `cc_is_subagent=true` 为权威信号，准确率 10/15→15/15）、**配置体检**（`doctor.py`，8 条只读规则）、**失败聚合**（`diagnose.py`，实测 2719 个失败→7 组），另含一轮 UI 可读性提升（`stop_reason`/`err_kind` 本地化、响应 Headers 面板默认展开并加粗 wire 层独有字段）与并行同模板子代理泳道撞车的修复。六自测全绿；打 tag 前经真实录制（866MB 那一天）验证无误报，并重新打包 exe 冒烟通过。
- **下一步**：
  1. **诊断闭环**：① 失败聚合的 UI 入口（目前只有 API/CLI）；② 反复出现的失败模式固化成体检规则（`effort_max_rejected_upstream` 即由此而来——标准：可复现？能静态判定？误报风险？）；③ 跨天趋势（最远，暂缓）。
  2. **判别残余**（暂缓）：交互模式（`cc_entrypoint=cli`）的子代理**未实测**（v0.4.0 本轮全是 sdk-cli）。两层规则保证 flag 缺席也不会再让主线被误判为子代理，但要彻底闭环需采集一次交互会话派生子代理的流量。

## v0.4.1 - 未发版

> 进行中——尚未打 tag。

### 新增
- **安全审查现在会说清楚「审的是什么、判成了什么」。** Claude Code 会在后台对 agent 的动作跑安全分类器——重度使用日里大约每六条请求就有一条是它（实测 388 条中 59 条，另一天 510 条中 175 条）。录制里这些数据一直都在，界面上却一样都看不出来：请求渲染成一个约 108,000 字符的折叠 `system` 块外加 170 多个平铺的 `messages` 块，**真正被审查的那个动作是第 174 块**，得一路翻到底；而列表行把响应摘要成 `<block>yes</`，恰好是能取到的最没信息量的 80 个字符。现在三件事都被抬到面上，解析只在 `classifier.py` 做一次（`sec_request` / `sec_verdict`），前端只负责渲染：
  - **在判定什么**——transcript 的最后一块，即 CC 正要执行的那条命令，拆成工具 + 参数。列表行现在读作 `审查：PowerShell · Set-Location …`，而不再是一段响应残片。
  - **判成了什么**——一个 chip，显示 `severity` 分数（0-100，**50 是放行/拦截的分界**）或 block/allow 判定，命中的规则名与上游给出的理由放在详情卡片里。解析只匹配开标签：响应以 `stop_reason=stop_sequence` 结束，wire 上真实的文本就是裸的 `<severity>8`、闭合标签被吃掉——要求成对标签的话，在真实流量上会 100% 解析失败。
  - **这次审查向上游发送了什么**——规则库（约 108 KB）、**你的 CLAUDE.md 全文**（约 14 KB，作为「用户环境与意图的上下文」发出）、以及随行的历史动作条数。这正是只有 wire 层视角才说得出来的事实。

  在真实录制上实测：`sec_request` 解析 59/59 与 175/175，`sec_verdict` 56/59 与 172/175，在 120 条非安全审查请求的抽样中误判为 0。那 6 条没有产出判定的请求逐条查清，而非一笔带过——3 条是上游超时，另外 **3 条是模型没有遵守要求的输出格式**：请求明确写着 `Respond with <severity>N</severity> ONLY. No other text.`，模型却开始就该动作写起散文，撞上 64 token 的上限被截断，这次审查实际上没有得出任何结论。卡片会如实标注（`未产出判定`，并给出 `stop_reason`）而不是渲染成空白——安全检查静默失效，正是本工具存在的意义所在。索引 schema 由 4 升到 5（待判定动作位于 transcript **末尾**，超出 `last_user` 的 2,000 字符截断范围），因此首次访问时索引会重建一次（866 MB 的一天约 5 秒，1.18 GB 约 7 秒；主 jsonl 文件不动）。`dev_seed.py` 补齐了三种判定形态——原先的安全审查样例形状在现实中并不存在，这条路径在 UI 自测里根本走不到。详见 issues/closed/260729_安全审查可读性.md。
- **[docs/报文解读.md](docs/报文解读.md)**——面向使用者的「CC 7 种请求」解读指南（main / subagent / title / compact / security / count_tokens / other）：每种是什么、报文长什么样、CC 为什么发、怎么认、易混点。含「别被表面特征骗」识别方法论（count_tokens 与 security 在 stream/output 上撞脸但毫不相关）与 system 三 block 结构说明。已从 界面导览 / 架构总览 / 文档维护策略 交叉链接。
- **关于页「检查更新」**——拉取 GitHub 最新 release 比对版本（12s 超时，网络不通降级为手动链接）。
- **详情页 system block 标注角色**——每个 `system[i]` chip 按内容标角色（计费头 / 身份声明 / 安全审查指令 / 压缩指令 / 标题指令），例如 security 那条 ~108K 字符的 `sys[1]` 现在显眼地标成「安全审查指令」，不再是个看不出名堂的折叠块。

### 变更
- **捕获列表为非 main 行加 kind chip**。主线不加标记；其余（title / security / count_tokens / compact / subagent / other）各加一个 chip（计数 / 安全 / 标题…），一眼看出每行是什么角色。后端 `_public_summary` 现带 `kind`（经 `classifier.classify_idx` 现算）。
- **备份份数从捕获状态卡移到设置页**。「备份 N 份」放在捕获页头部语境不通，现移至 设置 → 备份目录（「当前 N 份」）。
- **ttft 本地化**（zh 首字时间 / en ttft / ja 初回応答），列表行与详情头。
- **请求侧 thinking 块**改为 chip + bigText 工具条（翻译 / AI 解读），与响应侧统一。（CC 通常不在请求历史里带 thinking，故主要在它带的时候生效。）
- **详情页字段归属纠正**：`model` 与 `stream` 来自请求体，从响应 meta-row 移到请求侧。响应 meta-row 现只留响应侧字段（status / stop_reason / ttft / total）——model 从来不是服务器返回的，本工具不录制响应 model。

### 修复
- **关闭主线泳道联动隐藏其辅助调用**。时序图里关掉一条主线，原先挂在它上面的 title / security / count_tokens / compact 调用仍留在共用的 aux 列里、看不出属于谁。现在 aux 节点若其 `near` 边父泳道被隐藏也一并隐藏，空的 aux 列不再占位，泳道菜单加了联动提示。
- **移除响应区的成本估算（≈ ¥x · PRICING）**。它按官方刊例折算，对走第三方网关的用户（本工具受众的常见情形）并不准。原始 Usage token 数保留。
- **一条永远不会触发的角色标注，与一处没人会知道的分类失败。** v0.4.0 之后的代码复查，每条发现都以真实录制核对，而非仅凭推理判断：
  - 详情页 system block 的角色标注中有一条 `compact` 规则，匹配 `summarizing conversations` / `summary of the conversation`。以真实压缩请求实测（07-26 的 `req_fbab1f0` / `req_c012395`）：其 `system` 就是普通主线 prompt（`You are an interactive agent…`），压缩指令位于**最后一条 user 消息**——分类器判定 compact 依据的也正是这里。因此该分支及其三语 `sysRole.compact` 文案永远不会渲染。现已删除，并将实测结论写入函数注释，避免日后有人凭直觉再次添加。
  - `_public_summary` 在 `classify_idx` 失败时降级为 `kind: "other"`，且不记任何日志。一旦索引字段发生变动，整天的捕获列表会全部变成 `other`，而任何位置都不会有迹象——正是本项目自己归纳的反复出现的 bug 类型 ③。现已比照既有的写盘/索引失败计数器，加入计数与日志，并做有界处理（首次必记，此后每 100 次记一条），因为该函数按列表行调用，真出问题时会成片失败。
  - 删除 9 条死 i18n 键，均为此前功能移除后的遗留：`detail.usageNote`（已移除的成本估算）、`status.backups`（已迁至设置页的备份份数）、`row.probe`（已由 `kindLabel` 取代）。三语字典现已逐键一致，各 225 条。`.cap-row.probe` 这个 CSS 类沿用历史名称——它现在由 `isAux` 驱动（涵盖任意辅助调用，不再限于计数探针）——并加注释说明。

  验证：六项自测全绿；`kind` 实测 0.033 ms/行，且仅对分页窗口计算（DAG 路径不经 `_public_summary`），无性能回归；前端在隔离的 `CCWA_HOME` 中以 510 条真实录制复验——kind chip、三语 system 角色标注、无 raw key 漏出，泳道隐藏仍会带走其辅助节点（隐藏 56 节点的主线，总节点减少 78）。

### 文档
- **三份 README 改为以「何时需要它」「它帮人找到过什么」「它拿你的流量做什么」开场。** 仓库自 2026-07-12 公开，而落地页一直以技术类别开场——`MITM proxy`、`wire-level`、`SSE`。这对已经知道自己需要抓包的人足够清楚，对尚不知道它对应自己哪一个糟糕下午的 Claude Code 用户则是不透明的；而「MITM」加上「完整录制」，又会让人合理地担心把会话指向它是否安全。现在三份 README（en/zh/ja）改以三节开场：
  - **什么时候你会需要它**——三个可自认的场景（CC 走第三方网关而某处不对劲；想看清 CC 实际发送了什么——发送态的 system prompt、被派生的子代理、后台安全分类器调用、上游报告的 token 数；想把一次会话留档以便回头翻查）。同时明说谁**不必**费这个事：如果你用官方端点、一切正常、只想看对话历史，`~/.claude/projects/*.jsonl` 已经有了，而且更好读。
  - **一个真实案例**——v0.4.0 那次 effort/400 发现的完整链条：会话标题静默地不再生成、每条 title 请求都返回 `400`、上游自己那句点名字段的话、根因（`settings.json` 的 `effortLevel: low` 被环境变量 `CLAUDE_CODE_EFFORT_LEVEL: max` 盖掉），以及它如何变成配置体检的两条规则。真实脱敏录制数据，无 mock——并明说本工具不替你修任何东西：它让你看到发生了什么，并指出是哪个字段。
  - **把流量交给它安全吗**——四点：录制不出本机（并**显式列出**本应用自身的外发调用）、只编辑一个配置字段且退出即恢复、凭据脱敏但 body 原样存储故 capture 属敏感文件、以及它如何与官方直连 / 第三方端点 / cc-switch 共存。

  截图节上移至第一节之后——三段新增正文把它推到了三屏之外。详见 issues/open/260725_公开README入口与信任表达.md；该 issue 中剩下的一项（面向目标社区的发布素材包）有意未做：那属于对外动作，决定权在维护者。
- **README 不再手写版本号。** v0.4.0 曾在三份 README 顶部各加一行 `当前版本：vX.Y.Z`，因为 GitHub 渲染的 README 页面看不到当前 tag。**这行字在紧接着的那次发版就腐化了**——v0.4.0 已经发布，三份 README 仍写着 v0.3.2，直到三份独立的文档审计交叉确认才被发现。药方本身就是病灶：版本号的唯一真源是 git tag，README 抄一份必然分叉，而"每次发版改三个文件里的一行字"这种义务没人守得住。该行连同其维护者注释已删除，顶部只留 `发版列表 · 更新日志` 链接，GitHub 会让前者自动指向最新发布。这条通用教训已记入 [docs/文档维护策略.md](docs/文档维护策略.md)：**给文档腐化开的药方如果需要人工定期同步，它自己就是下一处腐化**——优先选零维护的指针，而不是可维护的副本。
- **`docs/AI_USAGE.md` 中文化，en/ja README 标注哪些文档是中文的。** 深度文档以中文撰写，而英文与日文 README 直接链过去却不加说明，读者只能点进去才发现。现在每个链接都标注 (ZH) 并附一行提示可用机器翻译。完整的多语言文档策略留待单独版本处理。
- **`docs/API契约.md` 修正，并从代码里删掉一个死字段。** `start` 响应中曾定义（并返回）恒为 `null` 的 `orphan_recovered`——前端实际只读 `/api/proxy/status` 的 `orphan_recovered_at_startup`。该字段已从 `src/app.py` 与契约文档中删除；`start` 的错误码枚举按代码核对更正，`err_kind` 中一个并不存在的 `parse` 值已删。

## v0.4.0 - 2026-07-28

### 变更
- **UI 可读性提升：技术枚举本地化，并凸显 wire 层独有字段。** 来自审计驱动的优化清单（[docs/界面导览.md](docs/界面导览.md) P1-P2），共三处改动。其一，`stop_reason`（`end_turn`/`tool_use`/…）与 `err_kind`（`upstream_4xx`/…）改为走 i18n 查表渲染（`stopReasonLabel` / `errKindLabel`，与已有 `kindLabel` 风格一致），三语覆盖、英文兜底，不再向非程序员直显 Anthropic API 的内部枚举值。其二，响应 Headers 面板改为**默认展开**（原先折叠），wire 层独有字段（`anthropic-ratelimit-*` / `request-id` / `anthropic-organization-id` / `x-should-retry`）以加粗 + 品牌色高亮，并附一行提示"仅在 wire 层可见，CC 的 jsonl 不记录"。其三，核实主线泳道头已采用"主线 N"序号。这些字段正是项目代码注释所称的"wire 层最有价值的信息"，原先的折叠状态使不知情者无从发现。详见 issues/closed/260726_P1-P2_前端微调批次.md。

### 修复
- **并行同模板子代理派生不再挤在同一条泳道。** 主线在一次响应中派生 N 个同类型 agent（例如 4 个 Explore），且派生 prompt 的前约 120 字相同（公共开场白 + 任务说明）时，泳道对齐会将 N 个子代理的首条 user 全部匹配到 `prompts[0]`，用同一个 lane_key 归入同一条 lane，导致 N 个 agent 在视觉上呈现为一色一列。根因与修复均位于 `classifier.py`：`PROMPT_PROBE_LEN` 由 120 提升至 300，`PROMPT_MATCH_LEN` 由 200 提升至 1000，`first_user_task` 由 600 提升至 1500，`IDX_SCHEMA` 由 3 提升至 4（首次访问时会 unlink 旧的 v3 索引并重建；维护者 866MB 那一天约耗时 5s，主 jsonl 文件不动，无数据丢失）。剩余约 5% 的边界情形（前 300 字仍完全相同）留待未来的双向匹配策略解决。详见 issues/closed/260725_并行同模板子代理泳道撞车.md。

### 文档
- **追平：让文档重新对齐代码，另加三份新指南。** 一次七视角排查（前端 / 后端 API / 数据链路 / 录制基座 / 外壳与测试 / 演进史 / 设计取舍）发现 8 处文档与代码不符的腐化。修复内容：
  - `docs/API契约.md`——补齐缺失的 `/api/health/config` 与 `/api/diagnose/errors` 节；将 `/api/translate` 和 `/api/explain` 改写为 SSE 协议（原文档描述为非流式）；说明 `usage` 字段名的双轨制（raw JSONL 使用 Anthropic 全名，列表/DAG API 出参使用 `classifier.usage_norm` 归一后的短名）；补充 `lane_id` 命名规则；删除 start 响应中恒为 null 的 `orphan_recovered` 死字段以及已删除的 `redact_headers` 配置键；补全 `/api/proxy/status` 的 `write_errors` 与 `external_change` 字段。
  - `docs/AI_USAGE.md`——新增维护者备注，说明 `usage` 字段双轨制，并添加兄弟文档链接。
  - 三份 README（en/zh/ja）——新增"当前版本"行与文档导航块。
  - `CLAUDE.md`——修正"死配置"教训的描述：三个配置（`retention_days`/`auto_start_proxy`/`redact_headers`）已于 260713 全部修复（前两个接线，第三个连同 UI 开关一并删除），保留作为历史教训对照。
- **新增三份文档**：[docs/界面导览.md](docs/界面导览.md)（4 个视图的人类审计视角 + 13 条按优先级排序的 UX 优化机会）、[docs/架构总览.md](docs/架构总览.md)（5 层架构 + 数据流 + 演进主线 + 设计哲学 + 8 条安全不变量）、[docs/文档维护策略.md](docs/文档维护策略.md)（元方法论：5 条防腐化策略 + 12 条当前腐化清单）。在每份核心文档的关键章节末尾添加"自检句"（"如果你改了 X，也要同步改 Y/Z"），使维护策略可执行。
- **CLAUDE.md 结构整理。** 本地 AI 接手文档堆砌感明显——"当前状态"单个 bullet 内塞了约 1700 字按版本堆叙事，反复出现的 bug 类型教训与子代理判别规则都混在速览里，未归入应属的"开发约定"。按工作区三段式骨架（速览 / 背景与目标 / 开发约定）重组：速览精简为 4 个 bullet；4 类反复出现的 bug 抽成表格；子代理判别规则独立成节；架构速记改用 ASCII 树状图；"评估"段补上 macOS 260714 真机全绿。不删除任何事实，仅调整位置并精简表达。详见 issues/closed/260726_CLAUDE_md_结构整理.md。
- **更新日志顶部新增「项目速览」段。** AI 接手快照（定位 / 当前状态 / 下一步）原先在本地 CLAUDE.md，现移至本文件顶部，让任何打开更新日志的人先看到项目当前状态。属规则/不变量的关键判断留在 CLAUDE.md（开发约定）；此处仅保留脱敏的公开导航视图。

### 新增
- **失败聚合：将录到的错误转化为 agent 可据以诊断的依据。** 重度录制日的时序图会被红卡填满，此后再无任何分析或处置：实测某日 2719 条失败请求，全部绘制出来，但一条都未被解释。更严重的是，重要的失败反而会被遗漏——本次发版涉及的 effort/400 发现在时序图中已存在数日，是在为其他事项截图时才偶然被发现。但失败请求并非噪声：**上游在返回时已经完成过一次诊断**，明确指出了哪个字段不正确、应改用什么。`GET /api/diagnose/errors`（以及 `cc-wire-analyzer errors`）按错误消息对当日失败进行归并——请求 id 与数字会被归一化，因此同一根因归为一组——并将**请求侧的字段与错误消息并列展示**：

  ```json
  {"count": 2, "status": 400, "message": "output_config.effort 'max' is not supported when thinking is disabled …",
   "kinds": {"title": 2}, "samples": ["req_8421a7c", "req_1b66772"],
   "req_fields": {"model": "claude-opus-5", "effort": "max", "thinking": "disabled", "tools_n": 0}}
  ```

  `req_fields` 即诊断依据：**单值**表示组内每条请求均为该值，**列表**表示该组跨越多个值。`effort: "max"` 与 `thinking: "disabled"` 均为单值，故病因在于 effort 设置；而 `model: ["glm-5.2", "glm-5v-turbo"]` 则说明模型并非这些失败的共同点。`kinds` 指出哪些请求类型受影响——仅限于 `title` 的失败只影响会话命名功能，其余一切正常。

  在 2993 条那一天实测：**2719 条失败 → 7 组，耗时 0.09 秒**，且分组即刻具备信息量——其中 2650 条为上游 504 超时，另有 19 条 `401 令牌已过期或验证不正确`，其 `model` 为 `claude-fable-5`/`claude-sonnet-5`，即官方模型名被发送到了第三方端点。输出有界（`limit` 默认 20，带 `truncated` 标志）：单条录制可超过 5MB，2719 条原始错误会直接占满 agent 的上下文。

  本模块只整理数据，**不调用 LLM、不进行分析**。推理工作留给读取它的 agent——这与本项目面向 AI 的其他接口是同一种分工。

- **配置体检：针对「CC 突然连不上」的只读诊断。** 在「官方订阅」与「第三方端点」之间反复切换，容易留下半成品的配置，而每一种半成品配置都会以难以归因的方式失败：BASE_URL 指向第三方却未配置 token（CC 会将订阅的 OAuth 凭据发送过去，必然被拒）、BASE_URL 仍指向早已无人监听的本地端口、订阅 OAuth 过期、effort 设置被上游拒绝。这些都不是本工具的 bug，但**只有本工具所处的位置能够观察到它们**：它同时读取 `settings.json`、知晓自身是否处于 patch 状态，还能看到上游的真实响应。与其逐一修补半成品配置引发的边界情形，不如在启动代理之前就将矛盾指出：
  - `GET /api/health/config` → `{ok, intent, patched, issues[]}`；CLI 的 `cc-wire-analyzer doctor` 向 agent 返回同一份数据。
  - 界面：`error` 级红色横幅、`warning` 级黄色横幅，并附一个**配置体检**抽屉，逐条列出具体字段、当前值与修改建议。
  - `POST /api/proxy/start` 会先执行体检，遇到 error 级问题时返回 **409 `config_unhealthy`**，避免在一个已经错误的配置之上再叠加一层代理（这正是此类状态难以排查的原因——`snapshot` 会将死端口记录为上游）。`?force=1` 可越过该拦截，横幅上也提供该按钮：规则可能误判，而用户比规则更了解自己的环境。

  三条约束：**绝不写入** `settings.json` 或凭据文件，也不提供自动修复（修改配置是用户的决定，而"只撤销我们仍能证明是自己做的那一笔改动"是本项目的既有不变量）；**宁可漏报不可误报**（误报的代价大于漏报——两次误报之后，便再无人关注横幅）；**绝不把用户锁死**。凡规则无法区分的情形，一律不予报告：loopback BASE_URL 若该端口**有人**在监听，可能是另一个实例或 cc-switch，故不报告；自身 patch 期间则穿透读取 marker 中的真实上游，不将自身地址当作残留；macOS 上凭据存储于 Keychain、文件确实不存在，OAuth 类规则静默跳过，而非报告"找不到凭据"。

  八条规则中有一条源自本次发版自己的录制数据，而非设计。真实录制显示，每一次会话标题请求都在失败：

  ```
  400 invalid_request_error: output_config.effort 'max' is not supported when thinking is
      disabled on this model. Use effort 'high' or below, or enable thinking.
  ```

  维护者本机的配置正是顶层 `effortLevel: low` 加 env `CLAUDE_CODE_EFFORT_LEVEL: max`——env 优先，于是会话标题功能一直静默失效，而 CC 界面上看不出任何迹象。这现已拆分为两条规则（`effort_level_conflict` 报告矛盾本身，`effort_max_rejected_upstream` 报告后果），后者以"上游确实是官方端点"为前提，因为第三方端点不会拒绝它。

### 修复
- **时序视图把子代理显示成主线，而在 SDK 模式下又把真正的主线降级成子代理。** 该问题来自 12 天前的真实使用反馈，此前一直无法修复：手头没有任何一次录制包含 `Task`/`Agent` 派生（三天共 194 条，派生数为 0），规则无从制定；脱离数据修改分类器等同于盲目猜测。本轮通过专门采集才得以定案——`claude -p` 串行派生 `Explore` / `general-purpose` / `Plan`，共 15 条录制，ground truth 由人工记录——并由此发现 **CC 自身已在 wire 上标注了子代理身份**，位置在 system block[0] 的计费头：

  ```
  main:     x-anthropic-billing-header: cc_version=2.1.220.8f8; cc_entrypoint=sdk-cli;
  subagent: x-anthropic-billing-header: cc_version=2.1.220.a83; cc_entrypoint=sdk-cli; cc_is_subagent=true;
  ```

  8/8 的子代理请求携带它，7/7 的非子代理请求不携带。无需任何启发式判断——而同一批数据也推翻了此前所有的假设：

  | 原假设 | 实测 |
  |---|---|
  | 子代理另起 `X-Claude-Code-Session-Id`，可作判别信号 | **复用父会话 id**（13 条同一个）→ session id 只能用作泳道键 |
  | `cc_entrypoint` 在子代理里变值 | 15/15 全是 `sdk-cli`，子代理**继承** |
  | CC 不给子代理派生工具（禁套娃）→「无 Agent 工具 ≈ 子代理」 | `general-purpose` 子代理**携带** Agent 工具（75 个） |
  | `system` block[1] 措辞可区分 | 15/15 完全相同（`"You are a Claude agent…"`） |

  工具数同样不是信号：同一条主线在一个会话内从 40 增长到 77（deferred tool 按需加载），与子代理的 62/75/71 完全重叠。

  四处修复，每一处均有实测依据：
  1. **`cc_is_subagent` 成为权威判据**，在任何主线指纹之前判定（子代理携带主线措辞，故按措辞排序必然失败）。
  2. **主线指纹表新增 `"you are an interactive agent"`**，未知形状的 fallback 从 `subagent` 反转为 `main`。原有的 `MAIN_SYSTEM_FP = "you are claude code"` 只在交互模式命中；SDK 模式下两处都不包含它，于是每条 `claude -p` 主线请求都落入 `tools_n > 0 → subagent` 而被降级——5/5 全错，正是旧准确率 10/15 的全部错项。
  3. **`build_dag` 不再跳过已判定为 main 的记录。** 此前那一行短路将全场最强的信号锁在门外：子代理一旦被误判为 main 就再也无法改判（"终身 main"），而每个被误判的子代理还会各自成为一条独立的"主线"泳道——正是用户看到的满屏主线。
  4. **派生 prompt 对齐从前缀匹配改为「剥掉 `<system-reminder>` 后子串匹配」。** 子代理的首条 user 与主线一样被注入 reminder 前缀，派生 prompt 被推到其后，两头 `startswith` 实测命中 **0/8**。剥掉 reminder 后，派生 prompt 逐字位于开头：8/8。（注入体量还随 agent 类型变化——`Explore`/`Plan` 约 550 字，`general-purpose` 携带完整 CLAUDE.md 约 9,960 字——因此定长前缀方案根本无法成立。）

  对照人工 ground truth 的准确率：**10/15 → 15/15**。采集当天的时序图从"0 主线 / 13 条分不清的子代理"且**零**派生边，变为 5 主线 / 8 子代理、**3** 条派生边，与实际派生次数一一对应。

- **同一个 CC 会话被切成多条「主线」泳道。** 旧泳道键是"首条 user 文本 + user_id"的 md5，其 docstring 自承在 autocompact 之后会断裂。实际断裂范围更广：866MB 基准日中，该 hash 分出 **42 个分组键，而真实会话只有 13 个**；更早的一天则将 2 个会话切分为 7+2。现改为以 CC 会话 id 作为泳道键（`X-Claude-Code-Session-Id`，回落至 `metadata.user_id` 内的 session id，两者都缺失时才回落旧文本 hash）——实测覆盖率 15/15 与 2993/2993。子代理与父会话共用 session id，因此按派生实例分组（派生者 id + 派生 prompt），同一个子代理的所有请求归入同一条泳道；此前泳道键取自记录自身的 id，导致同一个子代理的每条请求各占一列。

- **自测抢固定端口，端口被占时静默地去测了别人的实例。** `proxy_selftest` 将自身的 app 绑定在 5051；当已有 `serve` daemon 或 dev server 占用该端口时，Flask 在后台线程中 bind 失败，而主流程仍照常打印"已启动"，并将请求发送给**那个别的实例**——它的上游是真实端点，于是 fake token 换回 401，报错指向"转发损坏"这一完全无关的方向。它还向对方的录制写入了两条假请求。现改为：自测从 5150 起挑选空闲端口（避开工具自身的 5051–5100 区间），mock 上游端口回写至 fake settings 而不再写死，"app 已启动"也改为 `/api/proxy/status` 探活断言，而非 `sleep` 之后无条件宣布。验证方式：**在 dev server 占用 5051 的情况下**运行整套自测，全绿，且该实例的录制条数一条未变。

- **索引 schema 变化后，陈旧索引被静默复用。** `_read_idx_entries` 仅校验 `off`/`len`，因此在为索引记录增加字段后，旧索引依然"结构有效"——新字段在旧录制上读作缺失，分类器悄然退化为回落分支，而任何地方都不会报错。现改为：索引记录携带 schema 版本号，版本不符即整体作废并重建（须先删除文件，否则 append 模式的回填会追加在陈旧行之后，导致每次读取都重新触发一次重建）。实测重建：426MB 日耗时 5.3 秒，此后缓存命中 0.001 秒。

### 变更
- **配置体检现在会交代自己的边界。** `check()` 返回 `scope: "settings_file"` 并附一句说明，界面抽屉也直接写明：体检读取的是配置**文件**，而**正在运行**的 CC 会话保持其启动时的环境。用户刚修改完 `settings.json` 的那一刻，体检可能报告零问题，而其正在对话的会话行为依旧——这是当场观测到的：删除 effort 配置后体检立刻全绿，而运行中的会话仍是 `max`。**刻意否决了**"读取其他进程的环境变量以弥补该缺口"的方案：跨平台、权限敏感，且本工具常常根本不是 CC 的子进程（双击启动时即非）。无法区分的规则不予添加，改为如实说明自身覆盖范围。（`/api/diagnose/errors` 不存在此盲区：它查看的是**实际发生过的请求**。）
- **时序图泳道标签显示真实 CC 会话 id**（前 8 位，hover 显示完整 id），不再显示内部泳道 hash。该 id 与 `~/.claude/projects/` 下的 `.jsonl` 会话文件名一致，泳道可直接对应到具体会话。子代理泳道仍显示派生实例码：因其与父会话共用 session id，若也显示 session，便会与父主线标签完全相同。
- **`dev_seed.py` 的样例录制改为真实流量的形状**：3 块 system（计费头 / 身份声明 / 正文）、`X-Claude-Code-Session-Id` 请求头、`metadata.user_id` 为 JSON 字符串，子代理则携带 `cc_is_subagent=true` 计费头 + 被 `<system-reminder>` 包裹的首条 user。旧样例使用的是现实中不存在的形状（无计费头、无 session 头、裸派生 prompt），因此身份与会话逻辑在 UI 自测中一条都测不到——与 v0.2.0 放过四个 bug 的盲区同属一类。此外新增第二条子代理请求，覆盖"同一次派生的多条请求归入同一条泳道"。
- `tools/lane_probe.py` 输出权威位，并与分类器判断进行双向交叉核对，不一致时标记警告——其定位从"制定规则的工具"转为"更换 CC 版本时的回归探针"。

## v0.3.2 - 2026-07-19

### 修复
- **时序（DAG）视图在 1000 条处静默截断，大流量日下整个界面卡顿。** 重度录制日很容易超过 1000 条请求（实测：单日 2993 条 / 826MB，单条均值约 276KB），而链路上存在四个叠加的瓶颈：
  1. `list_full()` 将 DAG 输入写死在 1000 条——实测当天泳道图仅显示 1000 节点 / 5 泳道，而真实情况为 2993 节点 / 13 泳道，当日后 2/3 的内容根本未进入图。
  2. `list_captures()` 每次列表请求都 `readlines()` 整个主文件，并对最新的 200 行（恰是最大的行——上下文随时间增长）进行 JSON 解析：826MB 文件实测峰值内存 3.3GB、读盘 2.6s。
  3. `/api/dag` 每次调用都重读并重新解析整个录制文件，而前端在每条 LIVE 捕获事件后（800ms 防抖）都会重新调用——流量越大调用越频繁，单次也越来越慢。
  4. `get_capture()` 线性扫描并逐行 JSON 解析——打开一条详情最坏需解析整个 826MB 文件。

  根治方案：**写时轻量索引**。`append()` 时完整 record 本就在内存中，顺手将列表/泳道所需的全部字段连同主文件字节偏移写成 1~2KB 的索引记录（`{date}.idx.jsonl`）。列表和时序图只读索引（2993 条约 5MB，约 50ms），1000 条上限随之消失；详情按偏移直接 seek（实测 826MB 文件的最后一条仅 22ms）。索引记录自带偏移，索引缺失或落后（旧录制、崩溃断写）会从主文件增量回填自愈。索引写失败绝不阻塞转发（与主写同一不变量）——而是计数、记日志、经 `/api/proxy/status` 的 `write_errors.idx_count` 上报至 UI，并由回填兜底。前端：LIVE 更新已有的列表行改为单行 DOM 替换，不再每条 SSE 事件整表重建。

  826MB / 2993 条实测：DAG 1000→2993 节点（完整），一次性 5s 回填后构建耗时 147ms；列表 2.6s / 3.3GB → 1ms / 0.1MB；详情打开由数秒降至 22ms。

- **大流量日 LIVE 录制时时序视图冻结（前端），且 3000 节点的图无法阅读。** 即使后端索引已达毫秒级，每条 LIVE 捕获事件仍会触发前端全量重建——实测单次产出 1.7MB innerHTML（2993 个节点 div + 3725 条 SVG path），流量流动时约每秒一次约 1.1s 的主线程繁忙。布局按时间递增、新节点只可能追加在底部，因此 LIVE 更新改为**仅增量 append 新节点/新边**（实测 2ms，布局与全量重建逐节点比对完全一致）；全量重渲只在进入视图/切换日期/切换过滤、lane 数变化或节点档位改判时发生。工具栏新增两个过滤开关以提升大流量日的可读性：**隐藏工具循环步**（收起工具循环的中间步）与**隐藏辅助调用**（收起标题/安全/计数调用——实测占当日节点的 1/4），2993 节点的当日降至 2050 个可见节点 / 12 泳道。节点 CSS `transition: all` 收窄为具体属性。文案的中、英、日三语齐全。

### 新增
- **连续错误折叠成一张「×N」红卡。** 上游失效的一天会用重试错误灌满整张图（实测单日 2029 个错误节点——"错误永不降档"是刻意的设计规则，但 2029 张全高卡片将图撑至 16.8 万像素高，无法阅读）。同泳道的连续错误（≥2）现折叠为一张醒目的红卡，带数量、首末时间与首条摘要——参考日当日可见节点从 2993 降至 969。点击可展开为逐张错误卡（首张带"折叠"徽章，可收回）；LIVE 新到的错误原地更新数量，零重排。会话顺序/派生触发边会将折叠成员解析到折叠卡的位置。
- **时序工具栏泳道选择器。** 13 泳道的当日适应宽度后 zoom 仅约 29%，文字无法看清。新的"泳道"下拉列出所有泳道（色点、名称、条数），可逐个切换显隐；隐藏的泳道让出列宽，剩余泳道适应宽度后自然变大（仅留一条主线 + 子代理 + 辅助时 zoom 回到 100%）。切换日期时重置选择（泳道 id 每天不同）。

## v0.3.1 - 2026-07-18

### 修复
- **snapshot 自指致代理把请求转发给自己（v0.3.0 的 P0 回归）。** 当 `~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL` 指向本代理自身的本地地址（残留 patch 态 / cc-switch 切换至"录制端点"配置 / 手动修改）时，`snapshot_original()` 会将该自指地址当作"真上游"记录。随后 `forward()` 将 CC 的请求转发给"上游"= 本代理自身 → 无限递归 → CC 的所有请求 504 GATEWAY TIMEOUT。而且 marker 会将 `original == listen` 的自指值持久化，导致 stop/重启都无法解套（restore 恢复到受污染的 original；跨重启的孤儿自愈反而为死循环续命）。v0.2.0 不受影响——没有 watcher，该代码路径当时不可达。三层修复：
  1. **`snapshot_original()` 自指守卫。** BASE_URL 解析到本代理自身（loopback 主机 + 同端口）时抛出 `SettingsGuardError` 拒绝启动，并附带通俗提示。端口精确比对，合法的本地 OpenAI 兼容上游（如 `:8080` 的本地 vLLM）仍然放行。
  2. **`check_orphan_backup()` 的 marker.original 守卫。** marker 记录的 `original` 若为本地回环地址（说明已被 v0.3.0 这个 bug 污染过），只清除 marker，绝不将自指值写回 settings.json（否则跨重启自愈反而为死循环续命）。
  3. **`proxy.forward()` 深度防御。** upstream 若等于本代理 patch 进去的监听地址，则拒绝转发，返回 502 + 通俗提示（snapshot 守卫是第一道，这是最后一道）。

  根因是"守卫函数存在但调用点缺失"——`_is_local_proxy_url()` 早已在 `check_orphan_backup` 和 `restore` 中使用，唯独 `snapshot_original` 与 `recover_from_orphan` 这两个"将外部读取的 URL 写入 `_original_base_url`"的入口漏掉了。补强为安全不变量：凡是从外部（文件/marker）读取 URL 并准备记为 original 或写回 settings.json 的入口，都必须通过自指检查。

## v0.3.0 - 2026-07-17

### 新增
- **时序（DAG）视图节点三档视觉分层。** 此前每条请求都是等大的卡片：用户一条消息后跟随着一长串工具循环，主线泳道被同等重量的节点填满，叙事被淹没。现按两个纯结构判据分档（不猜测语义，动手前已在三天真实录制上验证）：最后一条 user 消息含真实文本（而非仅有 `tool_result` 块）的请求是 **用户消息轮**的起点 → 完整卡片；工具循环回传 → **细条**（行高压缩 + 降低透明度，长循环段整体收紧）；整轮零工具调用的轮次（让 AI 回顾、追问、澄清）→ **💬 纯对话轮**，虚线边框。错误节点永不降档。图例以三语说明三档含义。
- **settings.json 外部修改监视。** 使用 cc-switch 切换端点（或手动修改文件）会覆写 `ANTHROPIC_BASE_URL`——CC 将静默绕过代理直连上游，而 UI 仍显示"运行中"，监控断档且毫无征兆。现改为后台线程每 2 秒比对一次值（读取几 KB 的 JSON；刻意不使用 mtime 基线——patch 后存在竞态窗，也不引入文件事件库依赖）。发现不符即置为"已断开"状态、清除 marker、**绝不回写文件**（新值代表用户的新意图），界面以红色横幅显示新上游并提供一键**重新接管**——其本质即一次普通 start，snapshot 会自然收编新上游。`/api/proxy/status` 暴露 `external_change` 字段，serve 模式下驱动它的 AI 同样能感知。
- **能回答「上次会话怎么结束的」的退出日志。** run.log 此前仅以副产品形式记录退出（一行 `restored BASE_URL`，且仅当代理在运行时）——07-15 的一次会话仅留下孤零零一行日志，如何结束无从知晓。现改为：启动横幅（`=== started mode=gui|serve pid=… version=… port=… ===`）、每条可落笔的退出路径的显式记录（关窗、GUI 收尾、API 手动停止、atexit、信号），以及孤儿自愈触发时的一句通俗提示"上次进程未正常退出（强杀/断电/崩溃）"。启动横幅后没有对应的退出行，即可判定为强杀。

### 修复
- `run.log` 此前按系统 locale 编码写入（中文 Windows 为 GBK），中文日志在任何 UTF-8 工具中均为乱码。现改为显式 UTF-8（历史 GBK 段不迁移）。
- release 发布 job 首次被 tag 触发即在 Checkout 阶段崩溃：`fetch-tags: true` 与 checkout 动作自身为触发 tag 拉取的 ref 冲突（"Cannot fetch both … to refs/tags/…"）。改为 checkout 后显式拉取 annotated tag 对象（release notes 的 fallback 来源）。

### 变更
- **release notes 现在取自 `CHANGELOG.md`。** 发布工作流此前使用的是 `generate_release_notes`，它按 pull request 分组列出条目——对这种单人直接提交（无 PR）的项目毫无意义，因此 v0.1.0 与 v0.2.0 的 release 页面只剩一行孤零零的 "Full Changelog" 链接，详细的 changelog 根本无人读到。现改为 release job 从本文件提取当前 tag 对应的段落（带 tag message 和占位兜底），release 页面会自动带上完整的 changelog。

### 新增
- 本更新日志的中文版 `CHANGELOG.zh.md`，与英文版保持同步。

## v0.2.0 - 2026-07-14

### 变更
- **合并为单一二进制。** 此前：GUI exe + CLI exe（51 MB，两个文件）。现在：一个 noconsole GUI exe，附带 `serve` 子命令。双击 → 供人使用的 GUI；`cc-wire-analyzer.exe serve` → 后台 HTTP 服务 + 代理，不开窗，供 agent 使用。agent 调用的是 GUI 早已在使用的同一套 HTTP API（`/api/proxy/*`、`/api/captures`、`/api/dag`）。其可行性在于：Windows 的 noconsole 二进制没有 stdout——CLI 子命令本就无法将结果打印回给 agent；HTTP 才是正确的通道。macOS 同样为单一二进制（它从未有 console / 窗口态的区分）。参见 [docs/AI_USAGE.md](docs/AI_USAGE.md)。`cli.py` 作为开发者便利保留在源码树中（`uv run python src/cli.py`），但不再打包或随发行版分发。

### 新增
- 界面复制支持：每个内容块上的**复制**按钮（折叠时也能复制全文）、**自定义右键菜单**，以及 **Ctrl/Cmd+C** 处理。pywebview 在 debug 模式之外会禁用 WebView2 的原生右键菜单，而其 WebKit 后端不构建 Edit 菜单——因此 macOS 上 Cmd+C 原本无响应。现改为复制完全由前端处理，两个平台行为一致。
- 详情视图中的**响应头面板**。代理一直在录制 `response.headers_safe`，界面却从未展示——等于丢弃了这一层最有价值的信息：`anthropic-ratelimit-*`、`request-id`、`x-should-retry`、上游实际服务的模型。
- `tools/lane_probe.py`——将区分主线与子代理的候选信号列出（`X-Claude-Code-Session-Id`、`cc_entrypoint`、是否携带 `Agent` 工具、system 块结构、派生 prompt 对齐），使分类器能对照真实流量校准，而非凭猜测。
- `CCWA_HOME` / `CCWA_CLAUDE_SETTINGS` 环境变量覆盖，以及 `src/cli_selftest.py`。本项目最危险的路径——改写用户的 `~/.claude/settings.json`——此前无法端到端测试，除非在用户真实的 Claude Code 配置上试验。现改为在临时目录中运行。

### 修复
- **退出时不恢复 `ANTHROPIC_BASE_URL`。** 恢复逻辑挂在 `webview.start()` 返回之上，但 macOS 的 Cmd+Q / 红点关窗走的是 `NSApplication.terminate:` → C 层 `exit()`，不展开任何 Python 调用栈，也不运行任何 `atexit` 钩子。`settings.json` 被留在指向一个已失效的本地端口的状态，**Claude Code 再也无法连接任何上游**——而且是在工具已经关闭之后。现改为挂到窗口的 `closing` 事件上——这是 pywebview 唯一同步派发的事件，也是 macOS 两条退出路径都会触发的那个。已在 macOS 上验证（pywebview 6.2.1）：红点关窗与 Cmd+Q 都会恢复 `BASE_URL` 并清除 marker——源码层面的假设（`closing` = 同步的 `Event(self, True)`，两条 Cocoa 退出路径都经 `should_close()`）在 6.2.1 依然成立。
- **陈旧的恢复 marker 可能删掉用户的配置。** `recover_from_orphan()` 仅依据 marker 文件即采取行动，从不检查 `settings.json` 当前的实际内容。如果 app 在 patch 状态下被强制终止、用户随后又自行设置了 `ANTHROPIC_BASE_URL`（例如使用 cc-switch），下次启动就会覆盖它——或者，对于 `had_key: false` 的 marker，**直接将该键删除**。现改为恢复仅在当前值仍等于我们 patch 进去的地址时才进行。（`_is_local_proxy_url()` 自 marker 重构后一直是一段零调用的死代码；该守卫现已恢复。）
- **保留天数是个死配置。** 设置页声称"超过 N 天的录制会自动清理"，但代码库中没有任何代码读取 `retention_days`。录制持续累积——13 条就已达到 5.6 MB。现改为在启动时强制执行，结果回传至界面，并提供 `clear --older-than N` 命令。
- **非流式响应丢失了 usage、内容块和停止原因。** 非 SSE 分支只在 JSON 的*顶层*查找 token 计数（恰好是 `count_tokens` 返回的形状），而正常的 `/v1/messages` 响应将它们嵌在 `"usage"` 之下；`content_blocks` / `stop_reason` 又只在 SSE 分支中解析。Claude Code 的**安全分类器调用正是非流式的**——它们在每个会话后台运行、用户不可见、却消耗真实成本（实测 551 input + 28,224 cached）。其成本被这个"专门用于揭示成本"的工具丢弃了。
- **失败的录制写入被静默吞掉。** 磁盘满、权限问题或文件被锁时，`append()` 吞掉 `OSError` 照常继续——而位于 `try` 之外的 LIVE deque 和 SSE 推送仍在照常触发。界面继续跳动新录制，磁盘上却什么都没落盘。现改为写入失败会被计数、记录、暴露至 `/api/proxy/status`，并以红色横幅展示。（转发仍然绝不被写入失败阻塞——这部分是对的。）
- DAG 节点的 token 计数永远为空，CLI 的 token 总数永远为 0：两者都读取短的 `usage.input` 键，而 SSE 聚合产生的是 Anthropic 的全名（`input_tokens`、`cache_read_input_tokens`）。键名归一化现在只在一个地方（`classifier.usage_norm`）——这个 bug 之所以出现两次，正是因为那段逻辑被多处复制。
- 上游错误的真实原因从不显示。代理在连接/超时失败时记录 `{kind, detail}`，但界面只渲染 `kind`/`status`/`body_snippet`——因此一次失败的上游连接只显示为一个孤零零的 `connect`，原因被丢弃。对调试工具而言，这颇为反讽。
- `auto_start_proxy` 是个死配置，与 `retention_days` 一样：设置页提供开关、如实地存储它，却从无代码读取它。现已接线。
- 自测的 mock SSE 使用了现实中不存在的 token 键名（`input`、`output`，而非 `input_tokens`、`output_tokens`），这正是上述键名错位一直未被发现的原因。已修复，并补充了一个非流式上游用例——整条非 SSE 路径此前从未被断言过。
- **长文本翻译静默失败。** `_llm_chat` 不发送 `max_tokens`（上游较小的默认值会截断长输出），并在 120 秒超时；失败时界面仅弹出一次 toast、翻译区留白，用户看到一个空的"重译"，且没有任何原因说明。现改为设置了 `max_tokens`、将超时提升至 180 秒并附带专属 `timeout` 错误码，**将错误持久化至结果区**（带 `error_code` + 上游 `finish_reason` 提示，如 length / content_filter），而非无声消失。已验证：一段 106K 字符的安全 prompt（截至 20K）约 38 秒译完。
- **带非 ASCII 字符的 API Key / Base URL** 会产生一段晦涩的 `'latin-1' codec can't encode…` traceback（HTTP 头为 latin-1）。从网页复制时，零宽空格与全角字符很容易混入。现改为在前端即予以拦截，给出一条可读、点名出问题字符的提示。
- 翻译/解读的输出有时会泄漏引擎包裹内容所用的 `<text>` / `<content>` 定界符标签。现改为从结果中剥离。

### 移除
- **独立的 CLI 二进制**（`cc-wire-analyzer-cli.exe`）——并入 GUI 二进制的 `serve` 模式（见"变更"）。下方的"头部脱敏"开关也一并移除。
- **"头部脱敏"开关。** 它从未生效（`_redact()` 一直被无条件应用），与其将其接线，不如直接移除：让它真正生效，意味着提供将 API key 明文写入录制文件的选项——而那些文件现在正被 agent 读取。脱敏是无条件的，不再假称为可选。
- `config.read_port()`——自 shell 不再是独立进程后即为死代码。

## v0.1.0

首个开源发行版。
