# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.34 已发布。工具面（CC 的能力清单）进了索引与盲区雷达——`tools` 报基线外的内置工具、`tool_changes` 报同一条泳道内工具集中途变化；`betas` 段补上判读要用的 hosts/cc_versions 归属；`/api/*` 的 404 会给最接近的端点。读一段录制走轮次骨架总结与 A→G 目标流（八视图 v0.4.33 已取消，静态的事后切分在实际使用中没有价值）；实时分析两层结构（G 整体目标、T 内环）、误目标留痕、headline、按轮读取如 v0.4.32。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 新增

- **看历史日期时，今天来的录制会在日期条上报到**（issue 260912_今日新录制在历史日期下无提示）。此前用户若先切到某个历史日期再开始录制，今天的录制会被 `flushSSE` 整批静默丢掉：`checkDayRollover()` 只在「用户本来就在看今天」时才切（260801 定的原则：不打断主动选了历史日期的人），而日期条上今天那一格压根不会出现——`dates_available` 只在 `fetchCaptures` 时刷新。用户只能自己想起来手动切。现在丢弃前先记一笔：把今天补进日期条、按 id 去重记一个待看计数，那一格显示徽标并高亮，点一下切过去即清零。**不抢焦点的原则保留**，列表与 total 也不被污染（260712 的幽灵「加载更多」是这么来的）。**没有新增任何轮询或请求**：capture 本来就由 SSE 推来，数据已经在手上，成本为零。

### 修复

- **时序页的 `×N` 计数色块在三套外观下对比度都不达标**（issue 260912_视觉整体走查结果）。主线 1 的泳道色 `#A66B13` 亮度 0.186 卡在正中间——白字 4.44、黑字 4.18，**两种字色都过不了 4.5**，而 `fgOnHex()` 只会按亮度在黑白里二选一，选完仍然不达标。新增 `inkBg()`：保持色相逐档压暗直到白字达标，色块底改用它。泳道身份靠色相认，压暗不影响辨认，也不动泳道色板本身（连线与图例共用那份）；`fgOnHex` 随之无人调用，删除。同一处理用在轮卡的子代理徽章上。这一处是 `contrast_probe.js` 逐视图跑出来的，目视没看出来。

### 文档

- **观察者提示词补上 `goal` 的判据与正例**（issue 260912_观察者提示词目标漂移判据）。`AI_USAGE.md` 的顶部主指令此前只定义了「修正」（`refine`）与「转折」（`turn`），`goal` 只在下方长契约里留了「整体目标本身变了」一句、没有任何例子；同一段还单边警示「别把又开了一件事记成目标变了」。**起因**：一台跨机现场用 0.4.34 的观察者跑 A→G 时，用户起初没说真实目的、中途要求连续跳变（精炼 CHANGELOG → 改工作区规范 → 删测试材料 → 合并栏目 → 删打包文档 → 重组 issue → 为原型阶段做准备），观察者把这一串压成了一个贯穿全程的总目标，只在末尾记一次 `goal`，被用户退回后连做两次 `rebuild_goal_flow` 才改对（最终三处 `goal`）。改动：三类变化在主指令里并列给定义、触发信号与正例；判据补成双向的一张小表（什么不算 `goal` / 什么确实是 `goal`）；「G」一词只留给整体目标，任务级一律说 T 或「该任务的首个迭代」；要求记 `goal` 时在 trigger 里写一句「为什么是 goal 不是 turn」——两者结构条件完全相同，写不出理由的通常就是 `turn`；新增第 9 条允许「整体目标尚未成型」成为可记录状态（`current.understanding` 首句写明当前整体目标，未明确就直写「用户尚未说明真实目的，目标逐步显现」），不要事后补造连贯；`mode` 补一句判据（随录制增长分批提交＝`incremental`，整场一次性重建＝`retrospective`）。`API契约.md` 的 `change` 表与两平面段同步同一口径。
- **同伴会话的消息收成一条可执行规则**。`origin=user` 但正文以 `Another Claude session sent a message:` 开头、随后是 `<teammate-message teammate_id="…">` 的，是别的 CC 会话发进这条泳道的消息（多 agent 协作时的空闲通知与审查汇报），不是真人，也不是子代理泳道里的 `[派生指令]`，而它照样占一个轮号。实测样本：`9287e1ca` 会话 46 条 `[用户]` 行里 28 条属于这类。此前这条判据散在多处，观察者按 `[用户]` 读会把子代理汇报当成用户的新要求，凭空造出目标变化。

### 变更

- **A→G 图把 G 和 T 的层级画出来**（issue 260912_AG图G与T视觉层级）。用户反馈「界面挺好看，但 G 和 T 一眼看上去不能区分」。此前 G 段头是一条顶线加 11px 小标签，T 段头是一条左线加 11px 小标签，两者只差边框方向和 10px 缩进，而下属的 T 卡片是全场最重的元素——层级是反的。现在每个 G 段有自己的底衬（主色淡雾 + 描边 + 顶线），把属于它的 T 全圈进去，「谁属于谁」直接可见；G 的编号做成实心徽标，标题提到 15px；T 的编号改成描边 chip、标题回到常规字重。颜色全部由 `--ag-key` / `--brand-ink` 经 `color-mix` 派生，不新增主题 token。底衬**不能**用负 z-index：`.ag-canvas` 自己有背景且不构成层叠上下文，负层级会退到更外层被画布背景整个盖住（实测完全不可见），改为插在连线 `svg` 之前靠 DOM 顺序压底；段高取决于本段 T 排完后的位置，先渲染再回填。
- **A→G 图改成二遍布局，卡片不再互相压住**（同一 issue）。此前每个块的位置按固定节拍常量算，而真实高度由内容决定：G 段头实测 67px 而节拍只留 64，于是**每一段都压住下面的 T 段头 2px**；T 段头只有 25px 却按 46px 留位，间距排下来是 12 / -2 / 21 / 30 / 48 的乱序。调大常量治不了根——段头一换行就又会压上去（260909 反馈「被挡住一部分」是同一病根的上一次发作）。现在生成时的 top 只作首屏近似位，渲染后 `layoutGoalFlow()` 按实测高度重排一次，再画连线；间距统一成 A→G 段 30、段与段 36、G 段头→T 段头 12、T 段头→卡片 10、卡片之间 20。卡片高度由钉死的 112px 改成 `min-height`、正文 clamp 2 行放到 3 行——钉死高度会把长一点的目标截半句，而位置又按同一个常量算，两件事本就连在一起。实测（1600px / 1180px 两档，含展开折叠任务与打开就地详情）：重叠 0 处，卡片全部落在各自 G 段内。
- **顶部「当前的理解与现状」重排**（同一 issue）。用户反馈展开后「字体怪、集中在一侧、小标题比正文还小、正文叠成一坨、①② 混在一起」。一句话汇报此前卡着 `max-width:46em`，宽屏上只占左半边；小标题 13px 比它领起的 14px 正文还小；观察者又常把要点写成一整段、序号埋在句中。现在汇报放开宽度上限、提到 18px 并加左色条，小标题提到 15px 加色点，两栏各自坐进一张卡片，正文行距放宽到 2.0；渲染时在 ①–⑳ 前补换行并按行拆段、序号行加悬挂缩进——只动显示，存储的 `current.understanding` 正文不变。
- **「录制分析agent行为」补上中英文之间的空格**（中文与日文各一处），与项目其它文案一致。
- **两处浏览器探针断言修正**。`observe_goal_browser.cjs` 里「页面正文逐字包含 `current.understanding`」改为去掉空白后比对：分条渲染加的只是空白，不改一个字，这样反而更贴合它要守的「页面不篡改观察者写的内容」。另一处 `[data-om-action="goal-anchor"]` 在 strict 模式下命中两个元素——首个 G 段没有显式目标变化可指时，段头自 260909 起就与 A 卡片共用这个 action，与本次改动无关，只是这个手动探针本机从没跑起来过（缺 playwright）所以一直没暴露；改为 `.ag-anchor [data-om-action="goal-anchor"]`。

## v0.4.34 - 2026-09-11

### 中文

#### 新增

- **工具面进索引与盲区雷达**（issue 260911_工具面雷达与beta归属）。索引新增 `tools_builtin`（内置工具名列表）/ `tools_fp`（内置+MCP 的联合指纹）/ `tools_mcp_n`（MCP 工具数），`/api/unknowns` 随之多出两档：`tools` 报不在 `classifier.KNOWN_TOOLS` 基线里的内置工具（snippet 直接给该工具的 description 片段，一眼看出它是干什么的），`tool_changes` 报同一条泳道内工具集前后不一致（value 是差集，如 `+TaskCreate,TaskGet,TaskList… -EndConversation,RemoteTrigger,SendUserFile`）。**起因**：09-11 查「CC 是不是有新功能」时，`Artifact` / `DesignSync` / `Monitor` / `PowerShell` / `PushNotification` / `SendFeedback` / `Workflow` 七个内置工具只出现在第三方链路的会话上，而索引里关于工具只有 `tools_n` 一个数字——这件事只能靠人打开 40 MB 主文件逐条扫才看得见，雷达一个字都报不出来。工具面是 CC 的能力清单，地位等同于 `anthropic-beta`。`mcp__` 前缀的工具不进基线、不参与未知判定，只记数量：那是使用者自己装的 MCP，报它会把真信号淹掉（与 degraded 从 block_keys 分流出去同一个道理）。**分组键是会话 + kind + agent_id 而不是会话**：首版按会话分组，当天 26 条「工具集变化」没有一条是真的——子代理复用父会话 id、并行子代理之间工具面各不相同、CC 自己发起的检索派发恒 `tools_n=1`，三者合起来就是 main↔subagent 来回翻牌。收口后 09-06 只剩 1 条真变化。详情页的 Tools 折叠同步高亮基线外的内置工具，并在标题显示 MCP 数量。
- **betas 段带归属**。`/api/unknowns` 的 `betas.new` / `betas.known` 现在带 `hosts` / `cc_versions`，`new` 段另带 `samples`。端点的判读第一步写的就是「先看 hosts」，而 betas 恰恰是唯一没有归属的那一段——09-11 的新 beta 正好单一 host 独占，判读要用的信息不在响应里，只能人工拉 `/api/captures?limit=300` 自己按 `beta` 聚合才确认得了。`known` 段不给 samples（上千条给 id 无意义），`new` 段必须给——那才是要接着查上下文的一段。
- **`/api/*` 的 404 会指路**。未命中的 `/api/*` 响应从 `{error, path}` 扩成带 `did_you_mean`（最接近的已注册端点，≤3 个，从 Flask url_map 现算，不维护第二份清单）与 `hint`（指向 `GET /api/ai-guide`）。起因：AI 消费者按别处的惯例第一反应调 `/api/status`（本工具叫 `/api/proxy/status`），旧 404 不给任何线索，只能继续猜。相似度比的是去掉 `api/` 之后的部分——所有候选都以它开头，带着比会让 `/api/logs` 这种根本不存在的东西也配出三个「最接近」；宁可返回空列表也不给错的指引。
- **`/api/grep` 的 coverage 说明未检索区**。新增 `not_searched`：HTTP 头（含 `anthropic-beta`）不在检索区，查 beta / 工具面走 `/api/unknowns`。起因：拿 beta 特性名去 grep，命中的全是别的对话正文里提到它的地方，一条真正带该 beta 的请求都搜不出来，而 `coverage` 只列了「搜过哪些正文区域」，看不出这件事。

#### 变更

- **`KNOWN_BETAS` 并入 `mid-conversation-tool-changes-2026-07-01`**。09-11 首次出现（CC 2.1.268，当天 47 条全在同一条第三方链路上），逐日回查 08-31～09-10 全无，`claude.exe` 二进制里能取到该字符串——是 CC 客户端声明的新能力，不是网关的形状差异。它的语义正是「工具集可在对话中途变化」，与本版新增的 `tool_changes` 档是同一件事的两面。
- **`IDX_SCHEMA` 18 → 19**。新增的三个工具面字段在旧索引里恒缺失，会让 `tools` 档恒空、`tool_changes` 恒无变化而不报任何错（静默降级）。升级后首次读取会重建当天索引。
- **`tests/dev_seed.py`**：工具名从 `Task` / `TodoWrite`（真流量里早已不存在）换成基线内的真实名字，否则 seed 出来的每一条都被新雷达报成「没见过的内置工具」，样例数据自己制造的噪声会盖住真信号；新增 E5 样例演示工具集中途变化（未知内置工具 + MCP 各一个）；docstring 补上「跑完立刻删」的警告——09-10 有 54 条合成记录因为跑完没删留在真实录制里，回头查协议演进时差点被当成真信号。

### English

#### Added

- **The tool surface now reaches the index and the blind-spot radar** (issue 260911). Three new index fields — `tools_builtin`, `tools_fp`, `tools_mcp_n` — and two new sections in `/api/unknowns`: `tools` reports built-in tools outside the `classifier.KNOWN_TOOLS` baseline (the snippet is the tool's own description, so what it does is answerable without a second call), and `tool_changes` reports a tool set that differs between consecutive requests on the same lane (the value is the diff, e.g. `+TaskCreate,TaskGet,TaskList… -EndConversation,RemoteTrigger,SendUserFile`). **Why**: while checking "does CC have new features" on 09-11, seven built-in tools (`Artifact`, `DesignSync`, `Monitor`, `PowerShell`, `PushNotification`, `SendFeedback`, `Workflow`) turned out to appear only on third-party-link sessions — and the index held exactly one number about tools, `tools_n`. Seeing that required scanning a 40 MB capture file by hand; the radar said nothing. The tool surface is CC's capability list, on par with `anthropic-beta`. `mcp__` tools stay out of the baseline and out of the unknown check (they are the user's own MCP servers; reporting them would drown the real signal) and are only counted. **The grouping key is session + kind + agent_id, not session**: the first cut grouped by session and produced 26 "tool changes" that were all false — sub-agents reuse the parent session id, parallel sub-agents differ from each other, and CC's own search dispatch always has `tools_n=1`. After the fix, 09-06 keeps exactly one real change. The detail page highlights off-baseline built-in tools and shows the MCP count in the Tools header.
- **The betas section carries attribution.** `betas.new` / `betas.known` now include `hosts` / `cc_versions`, and `new` also includes `samples`. The endpoint's own reading order starts with "look at hosts first", yet betas was the one section without it — and the new beta on 09-11 was single-host, so the deciding information simply was not in the response. `known` gets no samples (ids are meaningless across thousands of rows); `new` must have them, because that is the section you follow up on.
- **404s on `/api/*` now point somewhere.** The response gains `did_you_mean` (closest registered endpoints, computed from Flask's url_map so there is no second list to drift) and `hint` (pointing at `GET /api/ai-guide`). An agent's first instinct is `/api/status` (here it is `/api/proxy/status`), and the old 404 offered nothing. Similarity is measured after stripping the shared `api/` prefix, and an empty list is preferred over a wrong steer.
- **`/api/grep` states what it does not search.** The new `not_searched` field says HTTP headers (including `anthropic-beta`) are outside the searched areas, and points to `/api/unknowns` for beta and tool-surface questions. Grepping a beta feature name only ever matched other conversations quoting it.

#### Changed

- **`KNOWN_BETAS` gains `mid-conversation-tool-changes-2026-07-01`** — first seen 09-11 (CC 2.1.268, all 47 on one third-party link), absent on every day from 08-31 to 09-10, and present as a string in the `claude.exe` binary: a capability declared by the CC client, not a gateway quirk. Its meaning — the tool set may change mid-conversation — is the other half of the new `tool_changes` section.
- **`IDX_SCHEMA` 18 → 19.** The three tool-surface fields are absent from older indexes, which would leave both new sections silently empty. The first read after upgrading rebuilds the day's index.
- **`tests/dev_seed.py`**: tool names switched from `Task` / `TodoWrite` (long gone from real traffic) to names inside the baseline, so seeded records no longer report themselves as unknown tools; added sample E5 for a mid-conversation tool change; the docstring now warns to delete seeded data immediately — 54 synthetic records left on 09-10 nearly passed for a real protocol signal.

### 日本語

#### 追加

- **ツール面をインデックスと死角レーダーに載せました**（issue 260911）。インデックスに `tools_builtin` / `tools_fp` / `tools_mcp_n` を追加し、`/api/unknowns` に 2 つの区画が増えました：`tools` は `classifier.KNOWN_TOOLS` の基準線にない組み込みツールを報告し（snippet はそのツールの description 断片なので、何をするものか一目で分かります）、`tool_changes` は同一レーン内でツールセットが前後で食い違ったことを報告します（値は差分）。**きっかけ**：09-11 に「CC に新機能があるのか」を調べた際、7 つの組み込みツール（`Artifact` / `DesignSync` / `Monitor` / `PowerShell` / `PushNotification` / `SendFeedback` / `Workflow`）がサードパーティ経路のセッションにしか現れないと判明しましたが、インデックスにはツールに関して `tools_n` という数字が 1 つあるだけ——40 MB の本体ファイルを人手で走査しないと見えず、レーダーは一言も報告しませんでした。ツール面は CC の能力一覧であり、`anthropic-beta` と同格です。`mcp__` 接頭辞のツールは基準線にも未知判定にも入れず、数だけ数えます（利用者自身が入れた MCP であり、報告すると本物の信号が埋もれます）。**グループ化キーはセッションではなく セッション + kind + agent_id**：初版はセッション単位で、当日 26 件の「ツール変化」が 1 件も本物ではありませんでした——サブエージェントは親のセッション id を共有し、並列のサブエージェント同士もツール面が異なり、CC 自身の検索ディスパッチは常に `tools_n=1` だからです。修正後、09-06 に残る本物の変化は 1 件のみ。詳細ページの Tools 折りたたみでも基準線外の組み込みツールを橙色で示し、MCP 数を見出しに出します。
- **betas 区画に帰属情報を付けました。** `betas.new` / `betas.known` に `hosts` / `cc_versions` が付き、`new` には `samples` も付きます。エンドポイント自身が「まず hosts を見よ」と書いているのに、betas だけが帰属を持たない区画でした。`known` に samples は付けません（数千件に id は無意味）。
- **`/api/*` の 404 が行き先を示します。** `did_you_mean`（最も近い登録済みエンドポイント、Flask の url_map から都度算出）と `hint`（`GET /api/ai-guide` への案内）を返します。エージェントはまず `/api/status` を叩きますが、本ツールでは `/api/proxy/status` です。誤った案内より空リストを優先します。
- **`/api/grep` が検索対象外を明示します。** `not_searched` を追加：HTTP ヘッダー（`anthropic-beta` を含む）は検索対象外で、beta やツール面は `/api/unknowns` で調べます。

#### 変更

- **`KNOWN_BETAS` に `mid-conversation-tool-changes-2026-07-01` を追加**。09-11 に初出（CC 2.1.268、当日 47 件はすべて同一のサードパーティ経路）、08-31〜09-10 は日ごとに遡って皆無、`claude.exe` バイナリにも文字列が存在——ゲートウェイ差ではなく CC クライアントが宣言した新機能です。その意味（ツールセットが会話の途中で変わりうる）は新設の `tool_changes` 区画と表裏一体です。
- **`IDX_SCHEMA` 18 → 19。** 新しい 3 フィールドは旧インデックスに存在せず、放置すると両区画が無言で空になります。更新後の初回読み取りでその日のインデックスを再構築します。
- **`tests/dev_seed.py`**：ツール名を基準線内の実在名に変更（`Task` / `TodoWrite` は実トラフィックにはもう存在せず、そのままでは生成データ自身が未知ツールとして報告されます）、会話途中のツール変化を示す E5 を追加、docstring に「実行後すぐ削除」の警告を追加——09-10 に残った合成 54 件が、危うく本物のプロトコル信号として扱われるところでした。
