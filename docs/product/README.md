# 产品理解与决策资料

本地阅读入口：构建后打开 `../../dist/manual/index.html`。页面整合需求、当前功能、使用方法及后续设计；它是生成物，不直接编辑。

我们的文档分工与迭代思路见[三类文档与项目协作](reading/AI_三类文档与项目协作.md)，HTML 顶部提供直达入口。

## 修改位置

- `data/product-v3.json`：定位、工作流、挂载关系与本版需求修订；编号保持稳定。
- `data/capabilities.json`：原能力库正文；现有/部分状态属于原始基线，不是新一轮验收结果。
- `data/gaps-v3.json`：新增设计；`manual-v3.json`：操作步骤。
- `data/*reading-v3.json`、`principles-v3.json`、`reference-v3.json`：挂入工作流的专题阅读。
- `data/implementation-v3.json`、`tutorial-v3.json` 与 `assets/`：带日期、基线及哈希的实现/截图证据。迁移没有重新验证其中的历史产品能力。
- `reading/`：产品专用读法与术语。开发和使用参考分别从 `../development/`、`../usage/` 的五篇 Markdown 读取；AI_USAGE 继续独立维护。

修改前先登记 issue；已确认的稳定开发规则进入开发约定或 CLAUDE.md，状态和需求决策分别更新对应数据与 issue，不用生成 HTML 替代规则源。

## 构建与验证

仓库根运行 `.venv/Scripts/python.exe tools/build/build_manual.py`。完整工作产物在 `build/manual/`；交付文件在 `dist/manual/`，包含单文件 HTML、Markdown、OPML、JSON。

运行 `node tests/manual/verify_manual.cjs` 验证独立 HTML、参考正文、搜索、图片、窄屏和导出。需要 Playwright；可通过当前环境的 NODE_PATH 指向已配置的 Node 模块目录，不在脚本中固定机器路径。验证结果写入 `build/manual-qa/`。

公开材料仅保留在 `public/` 冻结断面；本构建不更新它，也不生成站点。原 V1/V2、废弃开发参考 JSON、历史裁定报告及未消费图片没有迁入。
