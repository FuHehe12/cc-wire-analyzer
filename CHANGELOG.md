# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.31 已发布。实时分析聚焦 A→G，并与捕获双向可达：从一条请求可以跳到覆盖它的观测，从证据可以回到原始正文；观察 AI 建歪的 A→G 可以留痕重建。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 新增

- 观察 AI 可以**按对话轮**读录制：`/api/actions?turns=N` 一次取 N 轮，一轮是一次用户消息加它引发的全部步，取满就停，不在轮中间截断。响应新增 `turns` 清单（不给 `turns` 参数时也有），每轮说明取全没有、是不是残轮、起源是真人还是合成；**该轮还没被下一轮终结时标 `complete:false`**——录制可能仍在进行，读的人据此知道手里是半轮，拉齐后再补建，不拿半轮下结论。实测本机 54 步泳道：逐轮跟随 5 次读完，首次拉取从步分页的 144 万字符降到 34.7 万。
- 用户对选项提问的答复不再消失。`AskUserQuestion` 与 `ExitPlanMode` 的返回是用户的原话拍板，对话视图此前把它和普通工具输出一起剥掉了；现在标 `[答复]` 留在原位，提问那一行也从「用了 AskUserQuestion」改成给出问题与选项。续读时同样认得出来——问在这一步、答在下一步是链路上的真实次序。
- 账本行区分消息来源：`[用户]` 是真人，`[用户·命令]` 是斜杠命令注入，`[系统合成]` 是 CC 内部合成的伪轮，`[派生指令]` 是子代理泳道里上级 AI 的话。此前一律显示为 `[用户]`，观察者要逐条甄别哪句是真人说的——实测某天的对话里有 9 条内部检索伪轮被当成真人要求。

- 导出页改成**两层结构：G 是整体目标，T 是它的内环**。此前每条目标迭代都被编号成 G0、G1、G2……，一场只有一个整体目标的会话看上去像是换了十几次目标；现在整体目标一段一段列在外层（G1、G2……），任务区在段内，卡片按「T3·2」这样的任务内序号编号——换一件交付（`turn`）不再产生新的 G。任务区按任务分区并可折叠：真实观测（7 任务 11 次迭代）首屏从 11 张卡压到 7 张，不在跟进中的任务折成一行，点区头展开。页面顶部常驻 A/G/T 的一句话释义，读者不必事先知道模型。
- 契约新增 `change:"goal"`：整体目标本身变了（用户提出新的结果诉求）。结构条件与 `turn` 完全相同——它同样开一个新任务——区别只在语义：`turn` 是同一个整体目标下换一件交付，`goal` 是整体目标换了。旧数据一条不动，没有这个标记的观测仍显示为一个整体目标。
- 目标流可以给**误目标留痕**：status 事件新增 `mistaken`，表示某个 G 曾被相信、后来判定方向本身就错了——和 `superseded`（被后来的目标接替）不是一回事。事后判定仍只走事件，迭代自身的 status 不接受它，不往当时的记录里塞后见之明。页面把这样的 G 标红划掉留在序列里，任务折叠时区头也标出「· 误目标」，不会被折没。这条来自 260909 实测：一次性复盘把「误做 compare 档案检查页 → 用户打断纠正」压成了一句 trigger，那个错目标在 G 序列里从未存在过。
- 目标流可以声明**建模模式** `mode`：`incremental`（现场逐轮跟随）或 `retrospective`（事后一次性复盘）。它描述这份记录怎么建的，不描述被观察的会话，因此可以随时改，也能在 delta 里替换。页面按模式给一句提示，复盘模式明说「中途被推翻的目标可能没有留痕」。

### 修复

- 目标图不再出现卡片互相压住和连线交叉。分层后新增一趟按父节点位置的重心排序，消掉了「上一行 A、B，下一行却是 B 的孩子在左、A 的孩子在右」这种 X 形走线；卡片高度与行距改为固定节拍，算出来的位置和画出来的框对得上。真实观测在 1440／1280／390 三个宽度实测：25 个定位元素，卡片重叠 0、溢出画布 0、页面无横向滚动条；打开就地详情时详情列与卡片列不相交。

### 变更

- `/api/*` 的 JSON 响应显式声明 `charset=utf-8`。需要说明的是**这不是 Windows 读到乱码的解药**：响应体本来就是纯 ASCII 的转义 JSON，按哪种码页解都一样，乱码出在客户端把解析后的中文打到本地码页的控制台。真正的解法写进了接入说明与 API 契约（PowerShell 设 `[Console]::OutputEncoding`，Python 用 `-X utf8`）。

### 文档

- 契约与接入说明写清 G 与 T 是两个平面（换一件交付用 `turn`、整体目标变了才用 `goal`）、误目标与 `superseded` 的区别、`mode` 的用法，以及**给旧观测后挂目标流的路径**——直接对原来的 goal 条目 `update_item` 挂 `goal_flow`，历史不迁移不补标，不要另建条目形成双轨。`current` 两段的写作口径也写进契约：概览不是工作日志，一件事一句话、最多一个数字，判断性信息必须保留，过程与逐项数字沉进 G 与事件。
- API 契约补 `turns` 入参与出参字段、问答例外与来源前缀的判据；`AI_USAGE` 的外环观察流程改为按轮读、逐轮建模（先更新当前理解，目标实质变化才动 G）；三语接入说明同步。

## v0.4.31 - 2026-09-09

### 中文

捕获与实时分析互相跳得通，证据能回到原文；观察 AI 可以整体重建一份 A→G。

#### 新增

- 捕获详情新增「实时分析」：直接打开覆盖这条请求的观测；还没有观测时带着这段对话的范围过去，「复制接入说明」产出的正是这段范围的新建指令，不必另外查观测 ID。
- 证据里的请求编号新增「在捕获中打开」，回到该请求在捕获里的完整正文；观测范围不是当前日期时先切换日期，返回仍回到实时分析。
- 观察 AI 可用 `rebuild_goal_flow` 整体重建已有的 A→G。重建必须写明理由，上一版保留在条目历史里，页面显示「已重建」并可查看每次理由。

#### 修复

- 滚轮停在目标流画布上时页面无法滚动。
- 详情里的列表与引用比正文大一号；强调改用色条与字重，不再靠字号跳变。
- 观测下拉按「日期 · 泳道 · 名称」排列；外环没写标题时用当前理解或最初原话回落成一句摘要，不再是一整列「未命名观测」。

#### 变更

- 阅读区、说明块与目标流三列按可用宽度展开，中文行宽不再按字母宽度截断；就地详情高度随视口计算，展开 A 不再在下方留出整屏空白。
- 窄屏顶栏改为两行，标题与副标题不再被页签挤成竖排。

#### 文档

- 三语接入说明与界面指引补充重建与跳转用法；API 契约补 `rid` 范围解析、列表 `preview` 与 `rebuild_goal_flow` 的字段与错误。

---

### English

Captures and live analysis now link both ways, evidence opens its original request, and an observer can rebuild an A→G.

#### Added and changed

- Capture details offer Live analysis: it opens the observation covering that request, or carries the conversation's scope over so Copy setup notes creates the right one. Evidence opens the full capture, switching dates when needed.
- `rebuild_goal_flow` replaces an existing A→G. A reason is required, the previous version stays in the item history, and the page marks it as rebuilt.
- Reading areas, notes and the three goal-flow columns use the available width; CJK line length is no longer measured in digit widths. Inline details size to the viewport, and the narrow-screen header keeps its title on one line.

#### Fixed and documented

- The page scrolls again when the pointer rests on the goal-flow canvas. Lists and quotes in details match body type; emphasis uses colour and weight.
- Observation names lead with date and lane and fall back to the current understanding, instead of a column of untitled rows.
- Setup notes, the interface guide and the API contract cover `rid` scope resolution, the listing `preview` and `rebuild_goal_flow`.

---

### 日本語

記録とリアルタイム分析を相互に移動でき、証拠から元のリクエストを開け、観測 AI が A→G を再構築できます。

#### 追加・変更

- 記録の詳細に「リアルタイム分析」を追加。そのリクエストを含む観測を開き、無ければ会話の範囲を引き継ぐので「接続説明をコピー」がそのまま作成指示になります。証拠からは記録本文へ戻れ、日付も自動で切り替わります。
- `rebuild_goal_flow` で既存の A→G を全体再構築できます。理由は必須で、前の版は項目履歴に残り、画面に「再構築済み」と表示されます。
- 読解エリア・説明・目標流の三列が利用可能な幅に広がり、日本語・中国語の行長が数字幅で切られなくなりました。詳細の高さは視口に追随し、狭い画面の見出しも縦積みになりません。

#### 修正・文書

- 目標流のキャンバス上でホイールを回してもページが動かない問題を修正。詳細内の箇条書きと引用を本文と同じ字号にし、強調は色と太さで表します。
- 観測の一覧は日付とレーンを先頭に置き、題名が無い場合は現在の理解などで補うため「名称未設定」の羅列になりません。
- 接続説明・画面ガイド・API 契約に `rid` の範囲解決、一覧の `preview`、`rebuild_goal_flow` を追記しました。
