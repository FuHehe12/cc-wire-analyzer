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

（暂无。下一条改动记在这里，发版时定稿为版本段。）

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

## v0.4.30 - 2026-09-09

### 中文

实时分析聚焦 AI 怎样理解要求、怎样判断现状，以及目标如何修正或转向另一件事。

#### 新增

- 顶部新增“它对你要求的理解”和“它对现状的判断”，先看清双方是否理解一致，再按需查看原话与证据。
- A→G 目标流保留最初理解，区分同任务的“修正”和另一独立任务的“转折”。此前任务可折叠，未完事项与持续要求不会因切换任务而消失。
- 目标状态、核验和观察者的解释订正分别留痕。状态变化不再制造新目标，AI 自称完成不等于通过验收。

#### 变更

- 主画面收起“工作与发现”“原始步骤”“预测核对”，集中呈现 A→G。旧记录与接口保留；尚无目标流的观测可通过“复制接入说明”交给观察 AI 补充。
- 目标详情在同行展开，原话证据就地查看；三套外观保持一致，窄屏可定位目标和详情，刷新保留选择、展开与阅读位置。
- 观察 AI 可增量更新当前理解与目标变化，无需反复提交全部历史；支持跨批次引用条目、删除关系和简短写入回执。

#### 修复

- 观测写入遇到错字段、错层级或内容超限会明确报错，不再出现成功回执却未生效或内容被截断的情况。
- 账本续读到末尾后不再重复读取历史；可过滤辅助调用。修复复制接入说明后提示显示未翻译键名的问题。

#### 文档

- 更新三语接入说明与界面阅读指引，说明如何区分目标和现状、修正和转折，以及继续维护已有观测。刷新页面不会自动启动观察 AI。

---

### English

Live analysis now focuses on how the AI understands the request, sees the situation, and revises its goal or switches tasks.

#### Added and changed

- Two summaries show the AI's current understanding and view of the situation. A→G preserves the starting point and distinguishes revisions within a task from switches to another task, retaining unfinished work.
- Status, verification and observer corrections keep separate histories. The main view focuses on A→G; legacy records and APIs remain available, and Copy setup notes explains how to add a goal flow.
- Evidence opens beside the selected goal. Three themes, narrow-screen navigation and refresh preserve a consistent reading experience. Observers can submit incremental updates, reuse references across batches and request compact replies.

#### Fixed and documented

- Invalid or oversized observation writes now fail explicitly. Empty incremental reads no longer reread history; auxiliary calls can be filtered. Fixed untranslated copy-success feedback.
- Updated setup notes and the interface guide. Refreshing the page does not start the observing AI, and an AI completion claim is not acceptance.

---

### 日本語

リアルタイム分析を、AI が要求をどう理解し、現状をどう判断し、目標を修正・別タスクへ転換したかに集中させました。

#### 追加・変更

- 現在の要求理解と現状判断を上部に表示。A→G は最初の理解を保持し、同タスクの修正と別タスクへの転換を区別して、旧タスクの残件も残します。
- 状態・検証・観測者による解釈訂正を別々に記録。主画面は A→G に絞り、旧記録と API は保持します。目標流の追加方法は接続説明をコピーして確認できます。
- 選択した目標の横で原文・根拠を確認できます。三つの外観、狭い画面の移動、更新時の選択保持を改善し、観測 AI の増分更新と簡潔な応答にも対応しました。

#### 修正・文書

- 不正なフィールドや上限超過を明示的に拒否し、空の増分読み取りで履歴を再読しないよう修正。補助呼び出しの除外と、コピー後の翻訳済み通知に対応しました。
- 接続説明と画面ガイドを更新。画面の更新だけでは観測 AI は起動せず、AI の完了宣言だけで検収済みとは判定しません。
