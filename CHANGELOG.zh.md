# 更新日志

> 本文件是 [`CHANGELOG.md`](CHANGELOG.md) 的中文翻译镜像，与英文版保持同步，英文版为源。
> 已发布版本的完整说明在 [`CHANGELOG-history.zh.md`](CHANGELOG-history.zh.md)。
> 这里每条只写一行；原因、取证与被否掉的方案在 git commit 与本地 `issues/` 记录里。

## 项目速览

> 定位 / 当前状态 / 下一步——AI 接手快照。仅作导航；属规则/不变量的关键判断见本地 CLAUDE.md（开发约定）。条目里的 issue 路径是本地维护记录（gitignored，不在本仓库）。

- **定位**：本地 MITM 代理桌面应用，透明录制 Claude Code ↔ 上游端点的全部 HTTP 流量，填补 jsonl 日志与 OTLP 遥测看不到的链路级维度。双模式：GUI 给人看，`serve` 子命令暴露 headless HTTP API，让 AI agent 自己驱动排查——面向 agent 的说明书打包在产物里（`--help`，以及运行后的 `GET /api/ai-guide`），换一台机器用它不需要仓库。
- **当前状态**：**v0.4.22（2026-09-01）**——请求分类、轮边界与安全审查解析改用 Claude Code 自己声明的位与格式来判。
- **macOS 升级用户注意**（自 v0.4.2 起未变）：应用包由 `CCWireAnalyzer.app` 改名 `cc-wire-analyzer.app`，`/Applications` 里旧的那份不会被替换，需自行删除。
- **下一步**：
  1. 把「复发模式 → 体检规则」这一步自动化——`/api/diagnose/trends` 已能回答「新发还是老毛病」，但写规则仍靠人。
  2. 拍板失败重试该合并还是如实显示（某天 2,049 个「轮」里 2,000 个是三个真实问题的 504 重试）。
  3. 拍板轮起源该不该在运行时读 Claude Code 本地记录来纠正。现在不读，这份克制正是要点——数据面只有自己录的流量加 settings.json 一个字段。
  4. 压实之后的两件存储后续，都量过、都有意押后：骨架指针列表按增量存（估算 477 MB → 约 10 MB）；保留策略先压实、再把删除推迟很久。

## 未发布

### 新增

- 新的请求类别 `notify_eval`：你走开之后，CC 用来判断该不该叫你回来的那次调用。此前显示成 `other`。

## v0.4.22 - 2026-09-01

### 修复

- 会话命名类请求（标题、kebab-case slug）重新判为辅助，不再算主线。
- 对话形状但不带工具清单的请求不再判成主线。
- 工具连同结果一起返回的文本——图片说明、抓回的网页正文、打断标记——不再开启新的一轮。
- 轮边界此前有三份互不一致的实现，时序视图与分析视图现在共用一份。
- Claude Code 2.1.238 起录到的安全审查重新显示正确的待判定动作，历史动作数也不再虚增。
- 时序图的安全节点补上判定结果，此前只显示在审什么。
- `tools/origin_probe.py` 在录制压实成 `.pack` 之后静默覆盖不到。

### 新增

- 盲区雷达新增 `mainline_suspect` 维度：判成主线、却缺少主线结构特征的请求。
- `tools/origin_probe.py` 新增三档对账（`--mode belong | turns | origin`）。

### 其他

- `IDX_SCHEMA` 15 → 17，索引会自行重建。

## 更早的版本

v0.4.21 及更早：[CHANGELOG-history.zh.md](CHANGELOG-history.zh.md)，或 [GitHub Releases 页](https://github.com/Fuhehe12/cc-wire-analyzer/releases)（同一份说明）。
