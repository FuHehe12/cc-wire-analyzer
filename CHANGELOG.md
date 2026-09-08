# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：已发布基线为 v0.4.29。260908 恢复发版流程（此前一段时间只做本地迭代）；`public/` 仍冻结，发版不更新它。实时分析标签页升级为目标—阶段—产物/核验的语义观测图（含结构化预测核对），外环读取面新增 `view=dialog` 纯对话视图（311 步泳道 6.0 MB→222 KB）。
- **下一步**：按负责人反馈，以 A→G 主导的观测页面和新版观察者任务书已在本地重做并验证，待现场试用；继续验证长时增量归组的判断质量。运行界面不代替宿主启动模型，也不自动判断目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 修复

- 根据真实体验反馈，观测写入不再忽略拼错或放错层级的字段：例如 `rel`、`set_cursor.next`、平铺的更新标题均返回明确错误，整批操作不落盘。正文、证据数量和撤回理由超限也明确拒绝，避免写入成功但内容被截断。已有记录仍可读取。
- 动作账本读到末尾后返回 `done:true`，空增量不再重新读取历史正文。新增 `include_aux=false` 排除辅助调用并保留子代理；每步标出真实泳道，续读位置仍使用过滤前的原始索引位置。

### 新增

- 观测关系支持精确删除并保留旧关系历史，`client_ref` 在同一观测的后续批次仍可使用，重名或歧义明确报错。提交可选择简短回执或只返回受影响条目，默认完整响应保持兼容；支持按单观测路径读取。软件内置接入说明补齐全部操作的字段与示例，无需猜字段名。
- 目标条目可维护 `goal_flow`：一次记录最初输入、AI 理解与自主取舍，随后追加由用户或 AI 推动的目标变化及证据，支持显式分叉汇合。初始理解和既有变化不可改写；观察者推断与明确表述分开，达成必须附用户验收或独立核验记录，软件不自动认证结论。

### 变更

- 实时分析以 A→G 目标流为默认主画面：最初理解、连续目标站点、显式分叉汇合与用户/AI 调整来源直接入图，选择站点查看前后差异、触发原因和证据。“工作与发现”“原始步骤”“预测核对”分开阅读，不再在首页纵向堆叠清单。非目标条目通过 `goal_iteration` 明确关联目标站点，同批最终校验并拒绝悬挂关联；旧数据保留未归属，不按时间或共同证据猜对应关系。窄屏查看分支后刷新保留横向与纵向位置，已有后继的旧目标不再误标当前进行中。
- 三语“复制接入说明”合并为一份以 A→G 为主任务的观察者任务书，带当前实例的地址、范围与续接入口。要求只在实质变化时追加 G，记录自主取舍与归因，按意图归组工作，保留改动、决定和失败，区分现场观测与回顾推断；补齐重连、版本冲突、原批重试及空轮询退避纪律。语义分析仍由外部观察 Agent 完成。

### 验证

- 17 项 Python 自测、18 条观测阅读 Node 检查及相关静态检查通过。两组隔离浏览器回归覆盖原有阶段/预测阅读与 A→G 主画面，验证真实父子连线、目标关联、三语、三主题对比度、390/768/1280 宽度、证据下钻和新修订刷新保留分支位置；复制提示词检查三语与新建/续接场景。体验包对话只用于本地复盘，未发布；尚未完成长时常驻外环的现场验收。

## v0.4.29 - 2026-09-08

### 中文

实时分析升级为目标—阶段—产物/核验的语义观测图，外环配套读取面新增纯对话视图。

#### 新增

- `/api/actions` 增加 `view=dialog` 对话视图：同一套增量与去重管线，只输出用户话语、AI 可见输出与思考，工具输入输出压成每步一行摘要（Bash 取命令首行、编辑类取文件路径、Task 派生取任务一句话）。给只需要"读懂这段会话讲了什么"的外环分析用——实测 311 步真实泳道从全文 6.0 MB / 4 页降到 222 KB / 1 页；子代理对话在其自己泳道的步里，用户消息中的 `<system-reminder>` 与斜杠命令回显剥除、`<command-name>`（如 /compact）保留。
- 实时分析改为目标—阶段—产物/核验关系图，保留关键未决问题、紧凑轮次与未覆盖请求入口；阶段按明确成员下钻，同页查看动作及工具返回证据，旧观测可折叠回退轮次阅读。
- 观测条目兼容新增 goal/artifact/check、短标题、独立执行进度与覆盖成员。连续阶段可用 cover_span 的首末请求 ID，由服务端校验同范围同泳道后展开，无需观察 Agent 枚举全部成员或编写布局。
- 结构化预测记录依据截止请求、后续主线窗口与可观察判断条件，封存原文；支持与反证单独核对，保留改判历史，不把观察者猜错等同执行者出错，不自动计算命中率。
- 只读 `/api/observations/trace` 增量投影：工具返回按同泳道先前调用 ID 配对，区分缺失、空结果与重复 ID 歧义，缓存只读新记录；原始动作账本保持现有格式。

#### 修复

- `/api/actions` 去重补上块级一层：同一段 AI 输出此前会出现两次——产生时标 `[说]`，下一次请求重发的历史里又以 `[助手]` 整段重出（消息级去重挡不住，因为响应块从未进过去重集合）。现在助手正文只在产生处输出一次；`[助手]` 前缀只剩"录制开始之前的历史"一种用途（其产生响应从未被录到，不丢录前上下文）。`since` 续读的预热阶段同步喂块级指纹，续读不会重放。
- 观测刷新增加请求取消与代次校验，防止快速切换后旧响应覆盖新观测；保留展开和选中状态，读取失败明确显示。水位不再误标成当前泳道执行步数。
- 接入说明补齐无观测时的 API 创建流程、来源/session 范围和语义维护方法；三语与三主题同步，修正窄屏选择器溢出和浅色主题的文字对比度。

#### 验证与文档

- 补充状态协议、范围展开、增量读取与前端语义回归，并接入现有 CI 验证；浏览器手动回归脚本覆盖目标阶段图、证据下钻、预测、修订刷新、三语三主题及 390/768/1280 宽度。适用原有自测通过，CLI 进程查询需允许 tasklist/taskkill 的本机环境。
- 用本地复制的54请求会话验证5个语义阶段、产物/核验及前缀预测回放，用247请求/18轮验证旧观测压缩。演示明确为开发期间外环复盘，真实录制与截图只留本地忽略目录，不随代码发布。使用说明、API合同、开发验证说明与本地说明书同步。

---

### English

The live-analysis view becomes a semantic observation graph (goals, phases, artifacts/checks), and the observer's reading surface gains a dialog-only view.

#### Added

- `/api/actions?view=dialog`: the same incremental, deduplicated pipeline with tool input/output compressed to one summary line per step (Bash → command, edits → file path, Task → its one-line description). For session-level analysis: a real 311-step lane drops from 6.0 MB / 4 pages to 222 KB / 1 page. Sub-agent conversations appear in their own lanes; `<system-reminder>` and slash-command stdout are stripped from user messages, `<command-name>` (e.g. /compact) kept.
- Live analysis rebuilt as a goal–phase–artifact/check graph with open questions, compact turns and an uncovered-requests entry; phases drill down to their member actions with tool-result evidence on the same page; legacy observations fold back into turn reading.
- Observation items support goal/artifact/check kinds, short titles, separate execution progress and covered members. Contiguous phases can use cover_span first/last request IDs, expanded server-side after same-lane validation.
- Structured forecasts freeze their basis request, horizon window and observable criterion; support and refutation are checked separately, revisions are kept, and a wrong guess is not conflated with executor error.
- Read-only `/api/observations/trace` incremental projection: tool results paired to prior same-lane calls, distinguishing missing, empty and ambiguous IDs; the raw action ledger is unchanged.

#### Fixed

- `/api/actions` dedup gains a block-level tier: the same assistant output used to appear twice — `[说]` when produced, then again as `[助手]` in the next request's resent history (message-level dedup never saw response blocks). Assistant text now renders once at origin; `[助手]` remains only for history recorded before capture began. `since` continuation pre-warms block fingerprints so it does not replay.
- Observation refresh gains request cancellation and generation checks, preventing stale responses from overwriting a newer observation; expansion and selection survive, read failures surface. The watermark no longer masquerades as the lane's step count.
- The onboarding copy covers API-first creation, source/session scope and semantic maintenance; synced across three languages and themes, fixing narrow-screen selector overflow and light-theme contrast.

#### Verification and docs

- State protocol, span expansion, incremental reads and frontend semantic regression added to CI; the manual browser script covers the graph, evidence drill-down, forecasts, revision refresh, three languages/themes and 390/768/1280 widths.
- A locally copied 54-request session validates five semantic phases with artifacts/checks and prefix-forecast replay; 247 requests / 18 turns validate legacy-observation compression. Demos are labeled as development-time retrospectives; real recordings and screenshots stay in local ignored directories.

---

### 日本語

リアルタイム分析を目標・フェーズ・成果物/検証のセマンティック観測グラフに刷新し、観測者向けの読み取り面に純対話ビューを追加。

#### 追加

- `/api/actions?view=dialog`：同一の増分・重複除去パイプラインで、ツールの入出力をステップごとに 1 行の要約へ圧縮（Bash はコマンド、編集系はファイルパス、Task はタスク一文）。会話レベルの分析向けで、311 ステップの実レーンが 6.0 MB / 4 ページから 222 KB / 1 ページに。サブエージェントの対話は自身のレーンに現れ、ユーザーメッセージの `<system-reminder>` とスラッシュコマンドの出力は除去、`<command-name>`（/compact など）は保持。
- リアルタイム分析を目標・フェーズ・成果物/検証グラフへ再構築。未解決問題・コンパクトなターン・未カバー リクエスト入口を維持し、フェーズはメンバーへドリルダウン、ツール結果の根拠を同ページで確認、旧観測はターン表示へ折りたたみ可能。
- 観測項目に goal/artifact/check 種別、短いタイトル、実行進捗とカバー メンバーを追加。連続フェーズは cover_span の先頭/末尾リクエスト ID で指定でき、サーバーが同レーンを検証して展開。
- 構造化予測は根拠リクエスト・対象ウィンドウ・観察可能な判定条件を凍結。支持と反証は別個に検証、改訂履歴を保持、観測者の推測ミスを実行者のミスと混同しない。
- 読み取り専用 `/api/observations/trace` の増分投影：ツール結果を同レーンの以前の呼び出し ID と対応付け、欠落・空・ID 曖昧を区別、キャッシュは新規記録のみ読み取り。

#### 修正

- `/api/actions` の重複除去にブロック段を追加：同じアシスタント出力が 2 回出る問題（生成時の `[说]` と、次リクエストの再送履歴による `[助手]`）。本文は生成箇所で 1 回のみ出力され、`[助手]` は録画開始前の履歴専用に。`since` 継続読み取りもブロック指紋を事前投入し、再放しない。
- 観測リフレッシュにリクエスト キャンセルと世代チェックを追加。急速切替時の旧応答による上書きを防ぎ、展開・選択状態を保持、読み取り失敗を明示。水位線をレーンの実行ステップ数と誤表示しない。
- 接続ガイドに API からの作成手順・source/session スコープ・セマンティック保守方法を補完。三言語・三テーマを同期し、狭画面のセレクター溢れとライトテーマのコントラストを修正。

#### 検証とドキュメント

- 状態プロトコル・範囲展開・増分読み取り・フロントエンド回帰を CI に接続。ブラウザ手動回帰はグラフ・根拠ドリルダウン・予測・改訂リフレッシュ・三言語三テーマ・390/768/1280 幅をカバー。
- ローカル複製の 54 リクエスト セッションで 5 つのセマンティック フェーズと予測リプレイを、247 リクエスト / 18 ターンで旧観測の圧縮を検証。デモは開発中の回顧と明記し、実録とスクリーンショットはローカル無視ディレクトリにのみ保持。

## 更早版本

v0.4.28 及以前的说明见 [CHANGELOG-history.md](CHANGELOG-history.md)。
