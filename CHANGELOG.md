# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：已发布基线为 v0.4.29。260908 恢复发版流程（此前一段时间只做本地迭代）；`public/` 仍冻结，发版不更新它。实时分析标签页升级为目标—阶段—产物/核验的语义观测图（含结构化预测核对），外环读取面新增 `view=dialog` 纯对话视图（311 步泳道 6.0 MB→222 KB）。
- **下一步**：本地实时分析已聚焦 A→G：顶部说明执行 AI 对要求的理解与对现状的判断，任务内修正、独立任务转折明确入图；沿用 Claude Code 的三套外观与就地详情。真实导出复盘和增量接口验证通过，待负责人体验。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

## 未发布

### 修复

- 根据真实体验反馈，观测写入不再忽略拼错或放错层级的字段：例如 `rel`、`set_cursor.next`、平铺的更新标题均返回明确错误，整批操作不落盘。正文、证据数量和撤回理由超限也明确拒绝，避免写入成功但内容被截断。已有记录仍可读取。
- 动作账本读到末尾后返回 `done:true`，空增量不再重新读取历史正文。新增 `include_aux=false` 排除辅助调用并保留子代理；每步标出真实泳道，续读位置仍使用过滤前的原始索引位置。

### 新增

- 目标流兼容新增 tasks、迭代 task_id/change 与可更新 current；任务内修正和新任务转折须显式声明且通过引用检查。update_item.patch.goal_flow_delta 可追加任务/G/事件、替换当前理解和现状，复用版本冲突、幂等与整批回滚；旧 A、任务、G 与事件不被重写。
- 观测关系支持精确删除并保留旧关系历史，`client_ref` 在同一观测的后续批次仍可使用，重名或歧义明确报错。提交可选择简短回执或只返回受影响条目，默认完整响应保持兼容；支持按单观测路径读取。软件内置接入说明补齐全部操作的字段与示例，无需猜字段名。
- 目标条目可维护 `goal_flow`：一次记录最初输入、AI 理解与自主取舍，随后追加由用户或 AI 推动的目标变化及证据，支持显式分叉汇合。初始理解和既有变化不可改写；观察者推断与明确表述分开，达成必须附用户验收或独立核验记录，软件不自动认证结论。

### 变更

- 目标状态与核验、观察者订正改为 `goal_flow.events` 的独立追加事件：同一个 G 可以后来达成、被替换或重新未决，不再为状态变化制造新目标；既有 A/G/事件不可覆盖，工作关联保持，旧数据兼容读取。
- A→G 图沿用 455ac9c 的三套外观、卡片阴影与第三列就地详情。顶部先呈现“它对你要求的理解”和“它对现状的判断”，点击才查看依据；窄屏对准目标列，详情宽度随视口收缩，修复画布居中却把目标卡片裁掉的问题。
- 三语观察提示词以当前理解与现状为首要输出，明确 G 是期望结果：目标或验收条件改变才增加 G，仅原因假设和现状改变只更新说明；持续约束和旧任务未完事项不能因转折消失。每段解释须能独立读懂，不能用“目标未变”等元总结代替实际要求。
- 实时分析暂时只显示 A→G，移去“工作与发现”“原始步骤”“预测核对”页签及默认发现列；旧记录与接口继续兼容，原文证据仍可按需打开。明确多任务时，此前任务默认折叠、当前任务展开；交错分支保持展开，避免折叠制造合并关系。单任务不增加任务层级。刷新保留任务展开、目标选择、详情和滚动位置。
- “复制接入说明”提供当前实例地址、范围与续接入口，改用 goal_flow_delta 提交小增量，并保留重连、版本冲突、原批重试及空轮询退避纪律。复制动作复用统一回退与三语反馈，修复成功提示显示未翻译键名。
- 目标图回到三套外观：此前那块画布把颜色硬编码成一套浅色并声明「与外层主题无关」，而同一块里的详情面板仍跟随主题，深色下就成了深色弹窗压在白板上；现在画布、站点、左右两栏、连线与阴影全部走 `--ag-*` 与宿主 token，深色/暖灰/浅色各一套取值，压字的强调色单列 `--ag-key`（`--brand-ink` 是给边框和实底的，暖灰下压字只有 4.2:1）。
- 目标详情保持在选中目标同行就地展开，增加画布宽度而不覆盖目标；关闭后收回详情列。原始证据从目标详情进入后仍留在同一行，异步加载结果也更新到就地面板。
- 目标卡片补回质感：站点与锚点按各外观的阴影档分层，选中态用更重的阴影加轮廓，取代此前统一的 `box-shadow:none`。

### 验证

- 260909 本轮：17 项 Python 自测通过，其中目标契约 26 条、scope/HTTP 23 条；25 条 Node 观测检查、6 场景三语提示词生成检查、四项静态检查、文档自测、compileall 和说明书构建通过。CLI 初跑受沙箱进程权限影响，双隔离重跑通过。两段真实导出重建 17 个前缀，25 组复盘检查通过，其中五次仅更新现状而不增加 G。CUA 实测三主题三语配对的 390/768 组件视口及桌面主页面，检查对比度、字号、溢出、就地详情、展开连线与刷新。真实复盘不是新盲测，不声称任务分割存在唯一标准；原始 HTTP 缺失处如实显示。
- 本轮17项Python自测、19项观测阅读Node检查和相关静态检查、说明书生成通过。真实导出共284请求重建11个前缀；另一个未获后续输入的观察者分3批读取其中216请求，生产契约、历史保留与证据截止检查通过，并检出多次验收条件变化。该单次观察不提供总体准确率；原始长输出与后续短句复盘分别保留。CUA检查实际页面和390/768组件视口，覆盖三语三主题配对、文字对比度、溢出、详情与刷新；新增本地预览仍未发布。

- A→G 模型补做真实导出复盘：两段共 284 个请求，15 个选定证据锚点核对与 7 次既有人工图结构前缀回放通过，但检出旧图遗漏两项后续表达纠正。协议反例复现同目标状态更新受历史冻结阻止、缺少外环订正归因、合法格式的虚构核验证据可被接受；状态与订正的表达缺口已由独立事件解决；证据格式通过仍不代表语义成立。该测试不代表总体语义准确率或现场常驻验收，原始材料与详细结果仅留本地。

- 17 项 Python 自测、18 条观测阅读 Node 检查及相关静态检查通过。两组隔离浏览器回归覆盖原有阶段/预测阅读与 A→G 主画面，验证真实父子连线、目标关联、三语、三主题对比度、390/768/1280 宽度、证据下钻和新修订刷新保留分支位置；复制提示词检查三语与新建/续接场景。体验包对话只用于本地复盘，未发布；尚未完成长时常驻外环的现场验收。

- 目标图表达层改动后重跑：17 项 Python 自测、22 条观测阅读 Node 检查（新增三条——AG 样式块内出现裸十六进制即失败、classic/light 两段的 `--ag-*` 键集必须与深色段一致、flow 页签开详情时详情须落在画布内的发现列且画布加宽）、四条静态对账与 compileall 全部通过；裸十六进制那条做过变异验证，故意加一行硬编码色确认闸门真会响。浏览器实测走隔离预览实例：`contrast_probe` 在三套外观下、详情开与关两态各跑一遍，对比度与行内字号跨度均为 0 处不达标；390 / 768 / 1600 三档宽度无横向溢出，窄屏经「发现与核验」定位按钮可读到详情。仍未发版。

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
