# 文档入口

[产品说明书](product-manual.html) 集中介绍产品要求、设计、实际操作、截图与开发参考，可独立离线阅读。

| 要做什么 | 阅读入口 |
|---|---|
| 了解产品、接入录制、查询与分析 | [产品说明书](product-manual.html) |
| 调用 HTTP 接口 | [API 契约](product-manual.html#doc=API契约.md) |
| 修改代码、运行验证、维护文档 | [开发约定](product-manual.html#doc=开发约定.md) |
| 用 agent 驱动已安装的软件 | [软件内置说明](reference/AI_USAGE.md)；也可用 `--help` 或 `GET /api/ai-guide` |
| 查看当前版本与变化 | [CHANGELOG](../CHANGELOG.md) |
| 搭建环境与提交贡献 | [CONTRIBUTING](../CONTRIBUTING.md) |

API 契约、开发约定和文档维护策略的旧 Markdown 路径只提供兼容跳转，正文在 HTML 中维护。`tools/doc_audit.py` 直接读取嵌入的开发参考，继续核对代码事实。软件内置说明和打包清单保持独立。

## 官网维护

中英文首页在 site/，共用 assets/site.css 与 site.js。先运行 python tools/build_site.py，再运行 python tools/site_audit.py；构建从产品说明书生成 site/manual.html，不手改、不提交这个副本。Pages 会在首页或说明书变更后重新生成并检查。

浏览器回归：node tools/site_browser_qa.cjs（需要 Playwright，可用 PLAYWRIGHT_PATH 指定安装位置）；它用本机 HTTP 子路径验证示例切换、语言、章节链接、下载和窄屏。分享预览图由 tools/render_social_preview.cjs 从 HTML 与示例截图生成。
