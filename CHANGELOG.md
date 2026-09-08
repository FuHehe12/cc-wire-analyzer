# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.30 待发布，已发布版本为 v0.4.29。实时分析聚焦 A→G：先呈现执行 AI 对要求的理解与对现状的判断，再查看任务内修正、独立任务转折和原话证据。`public/` 仍冻结，发版不更新它。
- **下一步**：完成发布检查与双平台构建，继续收集真实使用反馈。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

（暂无。下一条改动记在这里，发版时定稿为版本段。）

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
