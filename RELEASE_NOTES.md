<!--
tag: v0.4.37

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 新增

- 捕获详情页显示每条请求实际发给了哪个上游，悬停看完整地址。混用官方和第三方上游时，能看出某次失败是谁拒的。

### 变更

- 实时分析页的空白说明改成先讲你会遇到什么问题，再讲这一页怎么帮你。

### 修复

- 说明书生成脚本在 Python 3.11 下无法运行。

### 文档

- CHANGELOG 的写作要求移进开发入口文件，条目改成短句。
- 自测清单补回一项漏登的检查，它此前只在 CI 上跑。
- 架构总览里的接口清单补上漏掉的四十多个接口，并加了自动检查防止再漏。

## English

### Added

- The capture detail page now shows which upstream each request actually went to; hover for the full address. When official and third-party upstreams are mixed, you can tell which one rejected a given request.

### Changed

- The empty state on the live analysis page now leads with the problem you are likely hitting, then explains how the page helps.

### Fixed

- The manual build script failed to run on Python 3.11.

### Documentation

- The CHANGELOG writing rules moved into the developer entry file, and entries were shortened to single sentences.
- Restored a self-test missing from the checklist; it had only been running in CI.
- The architecture overview's endpoint list gained the forty-odd endpoints it was missing, plus an automated check so it cannot silently fall behind again.

## 日本語

### 追加

- キャプチャ詳細ページで、各リクエストが実際にどの上流へ送られたかを表示します。ホバーすると完全なアドレスを確認できます。公式と第三者の上流を混在させている場合、どちらが拒否したのかを判別できます。

### 変更

- リアルタイム分析ページの空状態の説明を、まず直面しがちな問題を述べ、次にこのページがどう役立つかを説明する順序に改めました。

### 修正

- 説明書の生成スクリプトが Python 3.11 で実行できない問題を修正しました。

### ドキュメント

- CHANGELOG の記述ルールを開発入口ファイルへ移し、各項目を一文に短縮しました。
- チェックリストから漏れていた自己テストを 1 件戻しました。これまでは CI でのみ実行されていました。
- アーキテクチャ概要のエンドポイント一覧に、抜けていた 40 件あまりを補い、再発防止の自動チェックを追加しました。
