# 文档导航

| 任务 | 当前真源 |
|---|---|
| 理解产品、需求与设计 | [product](product/README.md)；当前决定进入 `issues/open/` |
| 改代码时查规则 | [开发约定](development/开发约定.md) |
| 找模块边界与数据流 | [架构总览](development/架构总览.md) |
| agent 操作已安装软件 | [AI_USAGE](usage/AI_USAGE.md) |
| 查接口与字段 | [API契约](usage/API契约.md) |
| 看懂界面与报文 | [界面导览](usage/界面导览.md)、[报文解读](usage/报文解读.md) |
| 给其他 harness 做分析器 | [同类工具构建手册](guides/同类工具构建手册.md) |

Markdown 和产品源文件可编辑；`uv run python tools/build/build_manual.py` 将它们生成一本本地说明书，结果在 `dist/manual/index.html`。HTML 是阅读产物，不是另一份编辑真源。

`AI_USAGE.md` 随软件打包，必须在没有源码仓库时也足以完成操作；必要重复保留。维护规则见[开发约定第十一节](development/开发约定.md#十一改动流程issue-先行)。

历史依据与验收在 `issues/`，本地笔记在 `local/notes/`。`public/` 是冻结披露断面，本阶段不回写或同步。
