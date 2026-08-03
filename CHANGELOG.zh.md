# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步，英文版为源。
> 已发布版本的完整说明在 [`CHANGELOG-history.zh.md`](CHANGELOG-history.zh.md)。

## 项目速览

> 定位 / 当前状态 / 下一步——AI 接手快照。仅作导航；属规则/不变量的关键判断见本地 CLAUDE.md（开发约定）。条目里的 issue 路径是本地维护记录（gitignored，不在本仓库）。

- **定位**：本地 MITM 代理桌面应用，透明录制 Claude Code ↔ 上游端点的全部 HTTP 流量，填补 jsonl 日志与 OTLP 遥测看不到的链路级维度。双模式：GUI 给人看，`serve` 子命令暴露 headless HTTP API，让 AI agent 自己驱动排查——面向 agent 的说明书打包在产物里（`--help`，以及运行后的 `GET /api/ai-guide`），换一台机器用它不需要仓库。
- **当前状态**：**v0.4.9 已发布**（2026-08-03，紧急修复）。v0.4.8 的辅助聚合卡复用了普通节点的高度（62px），把分类计数徽章裁成了一条缝——标题/安全/计数的数量在 DOM 里有但视觉上看不出来；现在聚合卡有了自己的高度常量（`NH_AGG`=76）。最近两个视觉 bug 都收口了：把辅助泳道整个藏掉的折叠（v0.4.7）、把它找回来却裁掉计数的聚合卡（v0.4.8）。新增静态审计 `tools/check_render.py` 守住每张固定高度卡不再犯这类溢出，根因（六条自测全是后端 e2e、前端视觉零覆盖）已写进开发指南的惯犯清单。**macOS 升级用户注意**（自 v0.4.2 起未变）：应用包由 `CCWireAnalyzer.app` 改名 `cc-wire-analyzer.app`，`/Applications` 里旧的那份不会被替换，需自行删除。
- **下一步**：
  1. **把自迭代闭环走通**：`/api/diagnose/trends` 现在能可靠回答「新发还是老毛病」，但从「一个复发模式」到「一条体检规则」仍然靠人——`effort_max_rejected_upstream` 之所以存在，是因为有人盯出了那次复发并手写了规则。把这半自动化，雷达与趋势才不只是「读一读」。
  2. **判别残余**（暂缓）：交互模式（`cc_entrypoint=cli`）的子代理仍缺一次人工核对过的采集。历史录制已有统计旁证（225 条全部带判别位、零反例），但那与「采一次会话逐条对照 ground truth」不是一回事。
  3. 录制盲区审计（协议面 + 能力面）已于 v0.4.3~v0.4.6 收口，方法见 `docs/开发指南.md` 第二·五节与 `docs/问题域手册.md` 单元 0。

## v0.4.9 - 2026-08-03（紧急修复）

### 修复

- **辅助聚合卡的分类计数徽章重新可见。** v0.4.8 的聚合卡复用了普通节点高度（62px）装三行内容（时间行 / meta 行 / 分类徽章行 ≈ 72px）；卡片是 flex 纵列 + `overflow:hidden`，徽章行先被 `flex-shrink` 压扁、再被裁成 10px 一条缝——分类计数（标题 / 安全 / 计数）在 DOM 和 tooltip 里都有，视觉上却读不出来（「计数不见了」）。聚合卡现在有自己的高度常量（`NH_AGG` = 76）；`dagPlace` 全量与增量渲染共用，两条路径同时生效。值得给下一张固定高度卡记一笔：flex 会先在盒内把末行压扁、overflow 才裁，所以 `scrollHeight == clientHeight`——纯 overflow 判据测不出来，得量末行自身的高度。
- **CLI `errors` 现在返回 `ok: true`**，与其他十个子命令一致。此前唯独它没有这个顶层字段，agent 判 `data["ok"]` 会拿到 `undefined`。

### 新增

- **`tools/check_render.py`——静态审计固定高度卡的内容行数是否塞得下高度常量。** 最近两个视觉 bug（v0.4.7 藏掉辅助泳道、v0.4.8 裁掉聚合卡计数）的共同根因是：六条自测全是后端数据层 e2e，前端视觉完整性零自动化覆盖。项目无浏览器自动化（单 exe、无 playwright），运行时 DOM 溢出扫描无法自动化；改为维护一张「卡片 → 行数 → padding → 高度常量」表，断言 `行数 × 18 + padding ≤ 常量`，常量从 `const DGX={}` 实时解析，改常量不用改脚本。它能抓 v0.4.8 的形状（NH_AGG=62 会报 70 > 62）；`--self-test` 把 NH_AGG 改 62 验证检查确实会报。已加进开发指南的静态对账清单，与 `check_i18n_js`、`doc_audit` 并列。

## 更早的版本

v0.4.8 及更早：[CHANGELOG-history.zh.md](CHANGELOG-history.zh.md)，或 [GitHub Releases 页](https://github.com/FuHehe12/cc-wire-analyzer/releases)（同一份说明）。
