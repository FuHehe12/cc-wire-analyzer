# 变更记录

这里记录项目速览、未发布改动和当前版本。更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：已发布基线为 v0.4.28。本地文件体系已按产品、开发和使用分工，说明书可独立生成并包含三类文档的协作思考。260908 恢复发版流程（此前一段时间只做本地迭代）；`public/` 仍冻结，发版不更新它。本版新增给外环观测者用的上下文账本与观测状态接口，界面多一个「实时分析」标签页。
- **下一步**：让外环观测者真跑起来，据真实调用数据分析整段对话里哪些信息最占地方、最没用，再开按需调用的接口（见 `issues/open/260908_实时分析标签页与外环动作账本.md`）。预测—偏差单独立项，尚未开始。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## v0.4.28 - 2026-09-08

### 中文

给「外环观测者」开通读写：外环是另开的一个 AI，跟踪被观测 agent 做了什么、在做什么、接下来要做什么。

#### 新增

- `GET /api/actions`：把一条录制流还原成去重后的会话全文，一条 54 步主线由 19.8 MB 降到 241 KB，正文不截断；增量只有一个 `since`。
- `GET|POST /api/observations`：外环观测状态读写，幂等重放、整批生效、改判留痕。
- 「实时分析」标签页：观测清单按类分组，证据可点回具体请求。
- 详情页加泳道内前后导航与时序图定位。
- 本地说明书加入「三类文档与协作」章节。

#### 变更

- 恢复发版流程；`public/` 仍冻结，发版不更新它。
- 产品源可独立生成 HTML 说明书；测试与工具按职责分目录。

#### 修复

- 文档审计增加具名参考文档的正文检查。

#### 文档

- API 契约补两个新端点；开发约定恢复发版章节，自测清单增至十三条。
- 界面导览补详情页泳道导航；报文解读新增「拿网上流传的提示词对照录制」一节。
- README 改为人读入口；变更记录统一以中文为准，本版段另附英文、日文译文供发版说明用。

---

### English

Read and write paths for an **external observer** — a separate AI that tracks what the observed agent did, is doing and will likely do next.

#### Added

- `GET /api/actions`: a recording stream rendered as a deduplicated transcript; one 54-step lane drops from 19.8 MB to 241 KB with nothing truncated. `since` is the only incremental flag.
- `GET|POST /api/observations`: observation state, with idempotent retries, all-or-nothing batches and revisions kept on change.
- "Live analysis" tab: the observer's list grouped by kind, evidence links back to the exact request.
- Detail view: previous/next within a lane, plus jump-to-timeline.
- Local manual: new chapter on the three document roles.

#### Changed

- Releases resume; `public/` stays frozen and is not updated by a release.
- The manual builds from product sources; tests and tools split by role.

#### Fixed

- Doc audit now checks the body of named reference documents.

---

### 日本語

**外部オブザーバー**（対象エージェントの行動・現状・次の一手を追う別の AI）向けに読み書きの経路を追加。

#### 追加

- `GET /api/actions`：記録ストリームを重複除去済みの会話全文として返す。54 ステップのレーンが 19.8 MB から 241 KB に、本文の切り詰めなし。増分指定は `since` のみ。
- `GET|POST /api/observations`：観測状態の読み書き。再送は冪等、バッチは全件成立か不成立、改訂は履歴に残る。
- 「リアルタイム分析」タブ：観測一覧を種別ごとに表示、根拠から該当リクエストへ移動可能。
- 詳細画面：レーン内の前後移動とタイムラインへのジャンプ。
- ローカル説明書：「三種類のドキュメントと協働」の章を追加。

#### 変更

- リリースを再開。`public/` は凍結のままで、リリースでも更新しない。
- 説明書は製品ソースから生成。テストとツールを役割別に整理。

#### 修正

- ドキュメント監査が参照文書の本文も検査するようになった。

## 更早版本

v0.4.27 及以前的说明见 [CHANGELOG-history.md](CHANGELOG-history.md)。
