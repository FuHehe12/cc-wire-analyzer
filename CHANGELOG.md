# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.32 已发布。实时分析分两层读（G 是整体目标、T 是内环），误目标与建模模式可留痕，顶部两段可折叠并先给一句口头汇报；读取面支持按对话轮取。实时分析聚焦 A→G，并与捕获双向可达：从一条请求可以跳到覆盖它的观测，从证据可以回到原始正文；观察 AI 建歪的 A→G 可以留痕重建。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 中文

#### 变更

- **取消八视图**（issue 260910_取消八视图）。用户真机用过之后的结论是「静态的分析没有用」：八视图是事后静态切分（阶段/快照/血统/反事实），而看一段录制的真实需求由轮次骨架总结与目标流满足。删除范围：`src/trajectory.py` 整个模块（3305 行）；`GET|POST /api/snapshots/<id>/trajectory` 与 `GET /api/snapshots/<id>/semantic` 两个端点及其语义层管线；分析页的「八视图」档与切换器（轮次骨架只剩列表一档）、八视图归纳按钮、「复制指令·流程图」按钮（其数据源与文案整体建立在八视图字段上）；agent-brief 里的 trajectory 入口与字段清单；便携包不再搬运 `.semantic.json`（磁盘上已有的语义层文件不删——那是花过钱的归纳，只是不再有读取方，老包导入时忽略该成员不报错）。**轮次骨架总结（`/api/snapshots/<id>/analysis` 的步级简报+轮次归纳+线级总结）一字不动**。随取消消解两件 open issue（260829 只认 captures、260829 三语——押后理由里「翻完再裁是白翻」按最极端的方式兑现）。HTML 说明书在原八视图位置备注「已于 260910 取消」，不无声消失；产品数据（capabilities 的 I 组 11 项、product-v3 的挂载与张力标记、implementation 的代码证据）同步移除。验证：全自测 + doc_audit（端点对账）+ workspace_audit + i18n 三语 696 键同步 + 浏览器实测（分析页只剩列表档、`/trajectory` 与 `/semantic` 回 404、brief 端点不再列 trajectory、console 无报错）。

## v0.4.32 - 2026-09-09

### 中文

实时分析分成两层看：整体目标在外、任务在内；误做过的目标不再被复盘吸收；顶部两段能收起来，并且先给一句口头汇报。

#### 新增

- 观察 AI 可以**按对话轮**读录制：`/api/actions?turns=N` 一次取 N 轮，一轮是一次用户消息加它引发的全部步，取满就停，不在轮中间截断。响应新增 `turns` 清单（不给 `turns` 参数时也有），每轮说明取全没有、是不是残轮、起源是真人还是合成；**该轮还没被下一轮终结时标 `complete:false`**——录制可能仍在进行，读的人据此知道手里是半轮，拉齐后再补建，不拿半轮下结论。实测本机 54 步泳道：逐轮跟随 5 次读完，首次拉取从步分页的 144 万字符降到 34.7 万。
- 用户对选项提问的答复不再消失。`AskUserQuestion` 与 `ExitPlanMode` 的返回是用户的原话拍板，对话视图此前把它和普通工具输出一起剥掉了；现在标 `[答复]` 留在原位，提问那一行也从「用了 AskUserQuestion」改成给出问题与选项。续读时同样认得出来——问在这一步、答在下一步是链路上的真实次序。
- 账本行区分消息来源：`[用户]` 是真人，`[用户·命令]` 是斜杠命令注入，`[系统合成]` 是 CC 内部合成的伪轮，`[派生指令]` 是子代理泳道里上级 AI 的话。此前一律显示为 `[用户]`，观察者要逐条甄别哪句是真人说的——实测某天的对话里有 9 条内部检索伪轮被当成真人要求。

- 导出页改成**两层结构：G 是整体目标，T 是它的内环**。此前每条目标迭代都被编号成 G0、G1、G2……，一场只有一个整体目标的会话看上去像是换了十几次目标；现在整体目标一段一段列在外层（G1、G2……），任务区在段内，卡片按「T3·2」这样的任务内序号编号——换一件交付（`turn`）不再产生新的 G。任务区按任务分区并可折叠：真实观测（7 任务 11 次迭代）首屏从 11 张卡压到 7 张，不在跟进中的任务折成一行，点区头展开。页面顶部常驻 A/G/T 的一句话释义，读者不必事先知道模型。
- 契约新增 `change:"goal"`：整体目标本身变了（用户提出新的结果诉求）。结构条件与 `turn` 完全相同——它同样开一个新任务——区别只在语义：`turn` 是同一个整体目标下换一件交付，`goal` 是整体目标换了。旧数据一条不动，没有这个标记的观测仍显示为一个整体目标。
- 目标流可以给**误目标留痕**：status 事件新增 `mistaken`，表示某个 G 曾被相信、后来判定方向本身就错了——和 `superseded`（被后来的目标接替）不是一回事。事后判定仍只走事件，迭代自身的 status 不接受它，不往当时的记录里塞后见之明。页面把这样的 G 标红划掉留在序列里，任务折叠时区头也标出「· 误目标」，不会被折没。这条来自 260909 实测：一次性复盘把「误做 compare 档案检查页 → 用户打断纠正」压成了一句 trigger，那个错目标在 G 序列里从未存在过。
- 顶部「它对你要求的理解」「它对现状的判断」可以折起来了。真实观测上这两段占 549px，图要滚半屏才看得到；现在默认展开、点标题收起，收起后留一行摘要而不是只剩个标题，收起过就记住。实测收起后这块从 549px 降到 87px，图的起点从 y=843 提到 382。
- `current` 新增可选 `headline`：一句口头汇报，**硬上限 120 字符**。260909 实测的问题是这两段写得像工作简报——「当天依次推进七件事：①……②……」，读的人要读完七条才知道现在什么状况。程序管不住措辞，但管得住长度：一句话装不下清单，写的人只能挑最重要的说。页面把它放在最上面，也是折起后留在页面上的那一行；旧观测没有就没有，页面不会替它从长文里截一句。
- 目标流可以声明**建模模式** `mode`：`incremental`（现场逐轮跟随）或 `retrospective`（事后一次性复盘）。它描述这份记录怎么建的，不描述被观察的会话，因此可以随时改，也能在 delta 里替换。页面按模式给一句提示，复盘模式明说「中途被推翻的目标可能没有留痕」。

#### 修复

- 目标图不再出现卡片互相压住和连线交叉。分层后新增一趟按父节点位置的重心排序，消掉了「上一行 A、B，下一行却是 B 的孩子在左、A 的孩子在右」这种 X 形走线；卡片高度与行距改为固定节拍，算出来的位置和画出来的框对得上。真实观测在 1440／1280／390 三个宽度实测：25 个定位元素，卡片重叠 0、溢出画布 0、页面无横向滚动条；打开就地详情时详情列与卡片列不相交。

- 各视图顶栏此前是三种长相：捕获是 16/22 的大卡片，实时分析与分析是 10/14 的窄条，时序干脆没有容器；同一层信息在三处的字号也不同（11／11.5／12／13／14.5px）。统一成同一种 13/18 卡片与两档字号，日期行补上与顶栏同族的浅底容器，A→G 的 A/G/T 释义改成图例面板而不是正文里的小字。

#### 变更

- `/api/*` 的 JSON 响应显式声明 `charset=utf-8`。需要说明的是**这不是 Windows 读到乱码的解药**：响应体本来就是纯 ASCII 的转义 JSON，按哪种码页解都一样，乱码出在客户端把解析后的中文打到本地码页的控制台。真正的解法写进了接入说明与 API 契约（PowerShell 设 `[Console]::OutputEncoding`，Python 用 `-X utf8`）。

#### 文档

- 契约与接入说明写清 G 与 T 是两个平面（换一件交付用 `turn`、整体目标变了才用 `goal`）、误目标与 `superseded` 的区别、`mode` 的用法，以及**给旧观测后挂目标流的路径**——直接对原来的 goal 条目 `update_item` 挂 `goal_flow`，历史不迁移不补标，不要另建条目形成双轨。`current` 两段的写作口径也写进契约：概览不是工作日志，一件事一句话、最多一个数字，判断性信息必须保留，过程与逐项数字沉进 G 与事件。
- API 契约补 `turns` 入参与出参字段、问答例外与来源前缀的判据；`AI_USAGE` 的外环观察流程改为按轮读、逐轮建模（先更新当前理解，目标实质变化才动 G）；三语接入说明同步。

### English

Real-time analysis now reads in two planes: the overall goal on the outside, its tasks inside. A goal that turned out to be wrong is no longer absorbed by a retrospective pass. The two summaries at the top can be folded away, and lead with one spoken sentence.

#### Added

- Observing AIs can read a recording **by conversation turn**: `/api/actions?turns=N` returns N turns at a time — a user message plus every step it triggered — and stops there rather than cutting a turn in half. The response carries a `turns` list (present even without the parameter) saying whether each turn came back whole, whether it is a partial turn, and whether it started with a human or was synthesised. **A turn no later turn has closed yet is marked `complete:false`**: the recording may still be running, so treat it as half a turn and rebuild once it is complete. Measured on a 54-step lane: five reads to follow it turn by turn, and the first read dropped from 1.44M characters under step paging to 347K.
- A user's answer to an options question no longer disappears. Replies to `AskUserQuestion` and `ExitPlanMode` are the user's own decision, but the dialog view used to strip them along with ordinary tool output; they now stay in place marked `[答复]`, and the question line gives the question and its options instead of just naming the tool. Resumed reads recognise them too — the question is in one step and the answer in the next, which is the real order on the wire.
- Ledger lines name the source of each message: `[用户]` is the human, `[用户·命令]` is a slash command, `[系统合成]` is a turn Claude Code synthesised internally, `[派生指令]` is a parent AI speaking inside a subagent lane. Everything used to read as `[用户]`; in one day's conversation nine internal search turns looked like human requests.
- The flow page is now **two planes: G is the overall goal, T is its inner loop**. Every iteration used to be numbered G0, G1, G2…, so a conversation with a single overall goal looked like a dozen goal changes. Overall goals are now bands on the outside (G1, G2…), task groups sit inside them, and cards are numbered within their task (T3-2). Switching to another deliverable (`turn`) no longer creates a new G. Task groups fold: a real observation with 7 tasks and 11 iterations opens with 7 cards instead of 11.
- New `change:"goal"` in the contract: the overall goal itself changed because the user asked for a new outcome. Its structural conditions are identical to `turn` — it opens a task as well — and only the meaning differs. Existing records are untouched and still read as a single overall goal.
- A goal can be marked **mistaken**: a new `mistaken` status event says a G was believed and later judged wrong in direction, which is not the same as `superseded` (replaced by a later goal). The judgement still travels as an event; an iteration's own status does not accept it, so no hindsight is written into the original record. The page keeps such a G in the sequence, struck through, and marks it on the task band when the band is folded.
- A flow can declare its **modelling mode**: `incremental` (followed live, turn by turn) or `retrospective` (built in one pass afterwards). It describes how the record was made, not the conversation observed, so it can be changed later and replaced through a delta. The page says so, and for a retrospective record adds that goals dropped along the way may leave no trace.
- The two summaries at the top can be folded away, and when folded keep one line of gist rather than a bare label.
- `current` accepts an optional `headline`: one spoken sentence, **capped at 120 characters**. The wording cannot be policed by a program, but the length can — a single sentence has no room for a seven-item list, so the writer has to pick what matters.

#### Fixed

- Cards in the goal diagram no longer cover each other and wires no longer cross. Rows are now ordered by the position of their parents, which removes the X-shaped routing that appeared whenever two branches swapped sides; card heights and row pitch are fixed, so computed positions match drawn boxes. Measured at 1440, 1280 and 390 px on a real observation: 25 positioned elements, zero overlaps, nothing outside the canvas, no horizontal page scrollbar.
- The top bar of each view had three different shapes and five different type sizes. They now share one card and one type scale.

#### Changed

- JSON responses under `/api/*` declare `charset=utf-8`. Note this is **not** the cure for mojibake on Windows: the body is pure ASCII with `\uXXXX` escapes and decodes identically under any code page. The garbling happens when a client prints decoded Chinese to a console in the local code page; the real fix is in the caller and is documented in the usage notes.

#### Documentation

- The contract and setup notes now state that G and T are two planes, how `mistaken` differs from `superseded`, how `mode` is used, and **how to attach a goal flow to an older observation** — update the existing goal item in place; do not migrate or retag history and do not create a second item. The writing standard for `current` is written down too: an overview, not a work log.

### 日本語

リアルタイム分析を二層で読めるようにしました：外側が全体目標、内側がタスクです。誤りと判明した目標が事後の再構成に吸収されなくなり、上部の二つの説明は折り畳めるようになり、まず一文の口頭報告が来ます。

#### 追加

- 観測 AI が録画を**会話ターン単位**で読めます：`/api/actions?turns=N` は N ターン（利用者の発言と、それが引き起こした全ステップ）を返し、ターンの途中で切りません。応答の `turns` 一覧は、各ターンを取り切れたか、部分ターンか、人間から始まったかを示します。**次のターンがまだ終結させていないターンは `complete:false`** です。実測：54 ステップのレーンを 5 回で追い、初回取得は 144 万文字から 34.7 万文字になりました。
- 選択肢質問への利用者の回答が消えなくなりました。`AskUserQuestion` と `ExitPlanMode` の返答は利用者自身の判断ですが、従来は通常のツール出力と一緒に除去されていました。今は `[答复]` として同じ位置に残り、質問行にも設問と選択肢が出ます。
- 台帳の行が発言の出所を示します：`[用户]` が人間、`[用户·命令]` はスラッシュコマンド、`[系统合成]` は Claude Code が内部生成した疑似ターン、`[派生指令]` はサブエージェント・レーン内の上位 AI です。従来はすべて `[用户]` でした。
- フロー画面が**二層構造**になりました：G は全体目標、T はその内側のループです。従来はすべての迭代が G0、G1、G2… と番号付けされ、全体目標が一つの会話でも十数回目標が変わったように見えていました。今は全体目標が外側の帯、タスク区がその中、カードはタスク内番号（T3·2）です。別の納品物に移る `turn` では新しい G は生まれません。タスク区は折り畳めます（実観測：7 タスク 11 迭代が初期表示 7 枚）。
- 契約に `change:"goal"` を追加：全体目標そのものが変わった場合です。構造条件は `turn` と同一で、違いは意味だけです。既存データは変わりません。
- **誤目標を残せます**：status イベントに `mistaken` を追加し、一度信じて後に方向自体が誤りと判明した G を示します（後続目標に置換された `superseded` とは別物）。判定はイベントのみで扱い、迭代自身の status は受け付けません。画面ではその G を系列に残して取り消し線で示し、タスクを折り畳んでも帯に表示します。
- 目標流に**作成モード** `mode` を宣言できます：`incremental`（その場で逐次）または `retrospective`（事後の一括再構成）。記録の作り方の宣言であり、後から変更も差分での置換もできます。
- 上部の二つの説明を折り畳めるようになり、折り畳んでも要点の一行が残ります。
- `current` に任意の `headline`（口頭で伝える一文、**最大120文字**）を追加しました。言い回しはプログラムで管理できませんが、長さは管理できます。

#### 修正

- 目標図でカードが重なり、配線が交差する問題を解消しました。各行を親の位置で並べ替え、カード高さと行間隔を固定にしました。実観測を 1440／1280／390 px で計測：配置要素 25 個、重なり 0、はみ出し 0、横スクロールなし。
- 各ビューの上部バーは形も文字サイズもばらばらでした。共通のカードと二段階の文字サイズに統一しました。

#### 変更

- `/api/*` の JSON 応答が `charset=utf-8` を明示します。ただしこれは Windows の文字化けの対策では**ありません**：本文は `\uXXXX` エスケープの純 ASCII で、どのコードページでも同じに解釈されます。化けるのは復号後の日本語・中国語をローカルコードページの端末に出力する側であり、対策は呼び出し側にあります。

#### ドキュメント

- 契約と接続説明に、G と T が二層であること、`mistaken` と `superseded` の違い、`mode` の使い方、**既存観測への目標流の後付け手順**（既存の goal 項目をその場で更新し、履歴は移行も再タグ付けもせず、別項目も作らない）を明記しました。`current` の書き方（作業日誌ではなく概要）も契約に入れました。


