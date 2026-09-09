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
