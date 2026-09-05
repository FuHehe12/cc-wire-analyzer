# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步，英文版为源。 已发布版本的完整说明在 [`CHANGELOG-history.zh.md`](CHANGELOG-history.zh.md)。 这里每条只写一行；原因、取证与被否掉的方案在 git commit 与本地 `issues/` 记录里。

## 项目速览

> 定位 / 当前状态 / 下一步——AI 接手快照。仅作导航；属规则/不变量的关键判断见本地 CLAUDE.md（开发约定）。条目里的 issue 路径是本地维护记录（gitignored，不在本仓库）。

- **定位**：本地 MITM 代理桌面应用，透明录制 Claude Code ↔ 上游端点的全部 HTTP 流量，填补 jsonl 日志与 OTLP 遥测看不到的链路级维度。双模式：GUI 给人看，`serve` 子命令暴露 headless HTTP API，让 AI agent 自己驱动排查——面向 agent 的说明书打包在产物里（`--help`，以及运行后的 `GET /api/ai-guide`），换一台机器用它不需要仓库。
- **当前状态**：**v0.4.26（2026-09-05）**——详情页终于摆出 CC 每次要了什么：调用参数整块原样可见，没见过的字段标橙。
- **macOS 升级用户注意**（自 v0.4.2 起未变）：应用包由 `CCWireAnalyzer.app` 改名 `cc-wire-analyzer.app`，`/Applications` 里旧的那份不会被替换，需自行删除。
- **下一步**：
  1. 把「复发模式 → 体检规则」这一步自动化——`/api/diagnose/trends` 已能回答「新发还是老毛病」，但写规则仍靠人。
  2. 拍板轮起源该不该在运行时读 Claude Code 本地记录来纠正。现在不读，这份克制正是要点——数据面只有自己录的流量加 settings.json 一个字段。
  3. 压实之后的两件存储后续，都量过、都有意押后：骨架指针列表按增量存（估算 477 MB → 约 10 MB）；保留策略先压实、再把删除推迟很久。

## v0.4.26 - 2026-09-05

### 新增

- 详情页新增调用参数折叠区：请求体除三大块外的字段原样摆出，没见过的键标橙。

## 更早的版本

v0.4.25 及更早：[CHANGELOG-history.zh.md](CHANGELOG-history.zh.md)，或 [GitHub Releases 页](https://github.com/Fuhehe12/cc-wire-analyzer/releases)（同一份说明）。
