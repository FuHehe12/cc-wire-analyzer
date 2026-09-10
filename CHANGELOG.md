# 变更记录

这里记录项目速览、未发布改动和当前版本。未发布改动与最近版本在这里，更早版本见[变更历史](CHANGELOG-history.md)；变更按新增、修复、变更或文档分类，说明问题、改动与必要影响，详细调查过程查 commit 与本地 issue。

## 项目速览

本节只作接手导航，长期规则在 CLAUDE.md 与开发约定中；文中 issue 指本地迭代记录。

- **定位**：本地 HTTP 代理桌面应用，透明记录 Claude Code 与上游的请求和响应，补充本地对话日志和 OTLP 指标无法提供的链路信息。人通过界面查看，Agent 通过本地 HTTP 接口分析；随软件提供的 `--help` 和 `GET /api/ai-guide` 无需源码仓库即可读取使用说明。
- **当前状态**：v0.4.33 已发布。八视图已取消（静态的事后切分在实际使用中没有价值），读一段录制走轮次骨架总结与 A→G 目标流；实时分析两层结构（G 整体目标、T 内环）、误目标留痕、headline、按轮读取如 v0.4.32。`public/` 仍冻结，发版不更新它。
- **下一步**：收集跨机使用反馈，继续改善理解偏差的呈现与任务边界识别。外部观察 Agent 负责解释，程序不自动判断语义正确或目标达成。
- **保留的产品问题**：把反复出现的故障转为检查规则，目前 `/api/diagnose/trends` 只能辅助判断是否复发；是否利用 Claude Code 本地日志修正轮次来源，尚未采用；存储方面仍有骨架指针增量编码和“先压实再清理”的后续方案。指针列表从约 477 MB 降到约 10 MB 是历史估算，尚非本轮实测结果。
- **macOS 升级提示**：自 v0.4.2 起，应用名由 `CCWireAnalyzer.app` 改为 `cc-wire-analyzer.app`，不会覆盖 `/Applications` 中的旧名称，旧应用需要自行移除。

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

