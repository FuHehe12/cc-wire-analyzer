# 本地说明书生成器

从仓库根运行 `python tools/build/build_manual.py`（Python 3.12）。入口调用 V3 生成器并交付 `dist/manual/`。

`layout.py` 集中定义仓库、产品数据、模板和构建路径；`build_product.py` 组装稳定节点与导出；`book_bundle.py` 内嵌图片、脚本及 Markdown 正文。模板和第三方离线渲染资源分别在 `templates/`、`vendor/`，许可见 `vendor/NOTICE.txt`。

构建只消费本仓库 `docs/product/`、`docs/development/`、`docs/usage/`；不消费 public 冻结副本或历史归档。历史证据标注保留，不随构建改成当前验收。
