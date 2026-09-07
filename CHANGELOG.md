# 变更记录

这里记录项目速览、未发布改动和当前版本。更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：已发布基线为 v0.4.28。本地文件体系已按产品、开发和使用分工，说明书可独立生成并包含三类文档的协作思考。260908 恢复发版流程（此前一段时间只做本地迭代）；`public/` 仍冻结，发版不更新它。本版新增给外环观测者用的上下文账本与观测状态接口，界面多一个「实时分析」标签页。
- **下一步**：本地语义轨迹与预测核对已集成，等待负责人检查真实演示；继续由外部宿主运行观察 Agent，验证长时增量维护的判断质量。运行界面不代替宿主启动模型，也不自动判断目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 新增

- 实时分析改为目标—阶段—产物/核验关系图，保留关键未决问题、紧凑轮次与未覆盖请求入口；阶段按明确成员下钻，同页查看动作及工具返回证据，旧观测可折叠回退轮次阅读。
- 观测条目兼容新增 goal/artifact/check、短标题、独立执行进度与覆盖成员。连续阶段可用 cover_span 的首末请求 ID，由服务端校验同范围同泳道后展开，无需观察 Agent 枚举全部成员或编写布局。
- 结构化预测记录依据截止请求、后续主线窗口与可观察判断条件，封存原文；支持与反证单独核对，保留改判历史，不把观察者猜错等同执行者出错，不自动计算命中率。
- 只读 `/api/observations/trace` 增量投影：工具返回按同泳道先前调用 ID 配对，区分缺失、空结果与重复 ID 歧义，缓存只读新记录；原始动作账本保持现有格式。

### 修复

- 观测刷新增加请求取消与代次校验，防止快速切换后旧响应覆盖新观测；保留展开和选中状态，读取失败明确显示。水位不再误标成当前泳道执行步数。
- 接入说明补齐无观测时的 API 创建流程、来源/session 范围和语义维护方法；三语与三主题同步，修正窄屏选择器溢出和浅色主题的文字对比度。

### 验证与文档

- 补充状态协议、范围展开、增量读取与前端语义回归，并接入现有 CI 验证；浏览器手动回归脚本覆盖目标阶段图、证据下钻、预测、修订刷新、三语三主题及 390/768/1280 宽度。适用原有自测通过，CLI 进程查询需允许 tasklist/taskkill 的本机环境。
- 用本地复制的54请求会话验证5个语义阶段、产物/核验及前缀预测回放，用247请求/18轮验证旧观测压缩。演示明确为开发期间外环复盘，真实录制与截图只留本地忽略目录，不随代码发布。使用说明、API合同、开发验证说明与本地说明书同步。

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
