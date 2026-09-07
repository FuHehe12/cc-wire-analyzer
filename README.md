# CC Wire Analyzer

CC Wire Analyzer 用来查看 Claude Code 与模型服务之间实际交换的信息。它在本机记录请求和响应，让你能检查模型收到了哪些提示词与工具结果、调用在哪里失败，以及时间和 Token 消耗在哪些环节。

当对话界面的提示不足以解释问题时，可以回到这里查原始记录：先找到相关请求，再读错误与返回内容，沿时间顺序检查重试和子代理调用，也可以保存快照作比较。人通过桌面界面查看；分析 Agent 可以通过本地 HTTP 接口查询同一批记录。

这个项目也在探索如何把运行证据用于改进 Agent 的工作条件：看清目标、执行和结果之间的差距，再判断该补资料、改工具说明还是调整规则。当前已有流量记录、查询与分析能力；可对话、可绘图的观测 Agent 等后续设计，在说明书中与现有功能分开标注。

## 接下来读什么

**先用这份 README 了解项目，再打开本地生成的 HTML 说明书（`dist/manual/index.html`，构建命令见下）。** HTML 按工作流展开功能、操作步骤、截图、设计与限制；顶部“三类文档与协作”解释负责人、开发 Agent 和使用软件的 Agent 如何分工。你可以从中理解项目、整理需求，再沿具体问题查看依据。说明书由源文件构建，不随仓库分发。

只有需要修改或核对某个细节时，再进入对应文件：

- 准备开发：读[本地工作约定](CONTRIBUTING.md)与[开发约定](docs/development/开发约定.md)；仓库根的 CLAUDE.md 是维护者本机的目录说明，不随仓库分发。
- 让 Agent 操作已安装的软件：读 [AI_USAGE](docs/usage/AI_USAGE.md)。
- 查看最近变化或历史演进：读[变更记录](CHANGELOG.md)和[变更历史](CHANGELOG-history.md)。
- 查正文放在哪里：读[文档导航](docs/README.md)。

## 在本机运行

启动桌面应用：`uv run python src/desktop.py`。环境和测试命令见[本地工作约定](CONTRIBUTING.md)。

如果还没有生成 HTML，运行 `uv run python tools/build/build_manual.py`，再打开 `dist/manual/index.html`。HTML 可单独复制阅读；修改内容应回到源文件，重新构建。

目前先在本地使用和改进这套工作方式。旧公开材料集中在 `public/` 保留为披露断面，暂不更新或发布。
