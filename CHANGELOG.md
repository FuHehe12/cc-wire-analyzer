# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.34 已发布——工具面（CC 的能力清单）进索引与盲区雷达，betas 段带上判读要用的归属，`/api/*` 的 404 会指路。v0.4.33 起八视图已取消。八视图已取消（静态的事后切分在实际使用中没有价值），读一段录制走轮次骨架总结与 A→G 目标流；实时分析两层结构（G 整体目标、T 内环）、误目标留痕、headline、按轮读取如 v0.4.32。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

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

## v0.4.33 - 2026-09-10

### 中文

#### 变更

- **取消八视图**（issue 260910_取消八视图）。用户真机用过之后的结论是「静态的分析没有用」：八视图是事后静态切分（阶段/快照/血统/反事实），而看一段录制的真实需求由轮次骨架总结与目标流满足。删除范围：`src/trajectory.py` 整个模块（3305 行）；`GET|POST /api/snapshots/<id>/trajectory` 与 `GET /api/snapshots/<id>/semantic` 两个端点及其语义层管线；分析页的「八视图」档与切换器（轮次骨架只剩列表一档）、八视图归纳按钮、「复制指令·流程图」按钮（其数据源与文案整体建立在八视图字段上）；agent-brief 里的 trajectory 入口与字段清单；便携包不再搬运 `.semantic.json`（磁盘上已有的语义层文件不删——那是花过钱的归纳，只是不再有读取方，老包导入时忽略该成员不报错）。**轮次骨架总结（`/api/snapshots/<id>/analysis` 的步级简报+轮次归纳+线级总结）一字不动**。随取消消解两件 open issue（260829 只认 captures、260829 三语——押后理由里「翻完再裁是白翻」按最极端的方式兑现）。HTML 说明书在原八视图位置备注「已于 260910 取消」，不无声消失；产品数据（capabilities 的 I 组 11 项、product-v3 的挂载与张力标记、implementation 的代码证据）同步移除。验证：全自测 + doc_audit（端点对账）+ workspace_audit + i18n 三语 696 键同步 + 浏览器实测（分析页只剩列表档、`/trajectory` 与 `/semantic` 回 404、brief 端点不再列 trajectory、console 无报错）。

### English

#### Changed

- **The 8-views trajectory analysis is removed** (issue 260910). The verdict after real use: static after-the-fact slicing was not what reading a recording needed — the turn-skeleton summary and the goal flow already answer that. Removed: the whole `src/trajectory.py` module (3,305 lines); the `GET|POST /api/snapshots/<id>/trajectory` and `GET /api/snapshots/<id>/semantic` endpoints with their semantic pipeline; the 8-views slot in the analysis page (the turn skeleton stays as the single list view), its summarise button, and the "copy flowchart brief" button (its prompt was built entirely on the 8-views fields); the trajectory entry and field list in the agent brief; `.semantic.json` is no longer carried in portable packs (files already on disk are kept — that summarisation cost money — they just have no reader any more, and old packs import cleanly by ignoring the member). **The turn-skeleton summary (`/api/snapshots/<id>/analysis`: per-step briefs + per-turn rollup + per-lane summary) is untouched.** Two open issues dissolved with the removal (260829 captures-only, 260829 i18n — "translate then cut" landed in its most extreme form). The HTML manual notes the removal in place rather than vanishing silently; product data (capabilities group I, product-tree mounts and tension marks, implementation code evidence) is updated in step. Verified: all selftests + doc_audit (endpoint reconciliation) + workspace_audit + i18n (696 keys, three languages) + browser check (analysis page shows the single list view, both endpoints 404, brief no longer lists trajectory, no console errors).

### 日本語

#### 変更

- **8ビューの軌跡分析を廃止しました**（issue 260910）。実使用後の結論：静的な事後分割は録画を読む要件ではなかった——その役割はターン骨格サマリーとゴールフローが既に担っています。削除対象：`src/trajectory.py` モジュ全体（3,305 行）、`GET|POST /api/snapshots/<id>/trajectory` と `GET /api/snapshots/<id>/semantic` の両エンドポイントとその意味層パイプライン、分析ページの8ビュー枠（ターン骨格はリスト一覧のみに）、その要約ボタン、「フロー図指示をコピー」ボタン（文言全体が8ビューの項目の上に立っていました）、agent ブリーフ内の trajectory 入口と項目一覧。ポータブルパックは `.semantic.json` を運ばなくなりました（ディスク上の既存ファイルは削除しません——お金をかけて作った要約です。読み手がいなくなっただけで、旧パックの取り込みは当該メンバーを無視して正常に完了します）。**ターン骨格サマリー（`/api/snapshots/<id>/analysis`：ステップ別ブリーフ＋ターン別まとめ＋レーン別まとめ）は一切変更していません。** 廃止に伴い open issue 2件を解消（260829 の2件——「翻訳してから切り捨てると無駄になる」が最も極端な形で現実になりました）。HTML マニュアルには元の場所に廃止注記を残し、無言で消えないようにしています。製品データ（capabilities の I グループ、product ツリーのマウントとテンション、implementation のコード証拠）も同期更新。検証：全セルフテスト＋doc_audit（エンドポイント突合）＋workspace_audit＋i18n（三言語 696 キー）＋ブラウザ実測（分析ページはリスト一覧のみ、両エンドポイントは 404、ブリーフに trajectory なし、コンソールエラーなし）。

