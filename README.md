# CC Wire Analyzer

本地开发与使用入口。记录 Claude Code 与上游的 HTTP 流量，供人和 agent 检查上下文、调用与失败证据。

| 要做什么 | 入口 |
|---|---|
| 理解产品、整理需求与作决定 | [产品资料](docs/product/README.md)，具体任务在 `issues/open/` |
| 修改项目 | [CLAUDE.md](CLAUDE.md) → [本地工作约定](CONTRIBUTING.md) |
| 用 agent 操作软件 | [AI_USAGE](docs/usage/AI_USAGE.md) |
| 查界面、API、架构或方法 | [文档导航](docs/README.md) |
| 看变化 | [CHANGELOG](CHANGELOG.md) |

启动桌面：`uv run python src/desktop.py`。生成本地说明书：`uv run python tools/build/build_manual.py`，结果在 `dist/manual/index.html`。

`public/` 保留冻结披露断面，当前本地修改不回写、不推送、不发布。原始录制存放位置由软件配置决定，不属于文档工作区。
