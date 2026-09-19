<!--
tag: v0.4.42

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 新增

- mac 首次安装提供标准安装镜像，双击打开后把应用拖入「应用程序」即可，从源头避免隔离运行导致的退回手动换版；原有压缩包保留供应用内更新使用。

### 文档

- 仓库首页新增安装说明：两个平台各给一条从下载到能用的最短路径，含首次运行时系统拦截的处理。

## English

### Added

- First-time macOS installs now ship as a standard disk image: open it and drag the app into Applications, which prevents the isolated-run state that used to push updates back to manual swaps. The zip archive remains for in-app updates.

### Docs

- The repository front page now has an installation section: the shortest path from download to a running app on each platform, including how to get past the first-run system prompts.

## 日本語

### 追加

- macOS の初回インストール用に標準的なディスクイメージを提供します。開いてアプリを「アプリケーション」へドラッグするだけで、隔離実行による手動置き換えへの退行を源から防げます。従来の zip はアプリ内アップデーター用に残ります。

### ドキュメント

- リポジトリのトップページにインストール手順を追加しました。各プラットフォームでダウンロードから起動までの最短経路と、初回起動時のシステム警告への対処を示します。
