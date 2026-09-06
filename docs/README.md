# 文档入口

> 读者：找这个项目某份文档的人和 AI。触发时机：不确定某个事实写在哪一篇时。

## 两种读法

**在线说明书**——[产品说明书](https://fuhehe12.github.io/cc-wire-analyzer/manual.html) 把产品要求、设计、实际操作、截图与开发参考聚合成一本，可在线阅读、可分享章节锚点。给想一口气读完的人。

**仓库内参考手册**——`docs/reference/` 下的 Markdown 是各篇正文的真源，可在 GitHub 上直接阅读、可 grep、可 diff。给要查某个具体事实、或要改文档的人和 AI。

📌 说明书是聚合的**阅读入口**，不是正文的存放地。正文改在 Markdown 里，说明书由构建从这些 Markdown 生成。

## 查什么读哪篇

| 要做什么 | 读哪篇 |
|---|---|
| 了解产品、接入录制、查询与分析 | [产品说明书](https://fuhehe12.github.io/cc-wire-analyzer/manual.html) |
| 调用 HTTP 接口 | [API 契约](reference/API契约.md) |
| 修改代码、运行验证、维护文档 | [开发约定](reference/开发约定.md) |
| 了解软件怎么搭起来 | [架构总览](reference/架构总览.md) |
| 认界面上的每一块 | [界面导览](reference/界面导览.md) |
| 看懂 Claude Code 实际发了什么 | [报文解读](reference/报文解读.md) |
| 用 agent 驱动已安装的软件 | [软件内置说明](reference/AI_USAGE.md)；也可用 `--help` 或 `GET /api/ai-guide` |
| 给别的 AI 工具做同类分析器 | [同类工具构建手册](../handbook/同类工具构建手册.md) |
| 查看当前版本与变化 | [CHANGELOG](../CHANGELOG.md) |
| 搭建环境与提交贡献 | [CONTRIBUTING](../CONTRIBUTING.md) |

`docs/文档维护策略.md` 只保留兼容跳转，正文在开发约定第十一节。软件内置说明（`AI_USAGE.md`）与打包清单独立维护——拿到软件的 agent 未必有仓库，那份必须自足。

`tools/doc_audit.py` 从 `docs/reference/*.md` 读规范正文，机械核对端点、枚举与代码事实。

## 链接怎么写

| 场景 | 写法 |
|---|---|
| 仓库内文档互引 | 相对 Markdown 路径，例如 `reference/开发约定.md` |
| 面向用户的「读说明书」 | Pages 在线地址 `https://fuhehe12.github.io/cc-wire-analyzer/manual.html` |

⚠️ 不要写 `docs/product-manual.html#doc=…`。那是构建产物，4 MB，GitHub 的文件页显示不出来（"we can't show files that are this big"），`#doc=` 锚点还依赖 JS 路由，在 GitHub 上不会生效。

## 官网维护

中英文首页在 `site/`，共用 `assets/site.css` 与 `site.js`。先跑 `python tools/build_site.py`，再跑 `python tools/site_audit.py`；构建从产品说明书生成 `site/manual.html`，不手改、不提交这个副本。Pages 会在首页或说明书变更后重新生成并检查。

浏览器回归：`node tools/site_browser_qa.cjs`（需要 Playwright，可用 `PLAYWRIGHT_PATH` 指定安装位置）；它用本机 HTTP 子路径验证截图放大、语言、在线章节链接、调查示例复制和窄屏。分享预览图由 `tools/render_social_preview.cjs` 从 HTML 与示例截图生成。
