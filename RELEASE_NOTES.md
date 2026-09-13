<!--
tag: v0.4.38

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 新增

- 捕获页多了「已冷藏」折叠区：很久没点开的日期自动收起来并再压小一截，点一下就解冻回日期栏。
- 设置里能关掉自动冷藏或改天数（默认 7 天），也能在捕获页手动冷藏某一天。

### 变更

- 实时分析页的字号收成六档，同一层级的内容不再各是各的大小。

### 修复

- 实时分析页点开一个目标时，显示的编号与图上那张卡对不上，会把一件任务读成整体目标。
- 捕获详情页里被上游加密的思考显示成空白，与模型压根没思考分不开。现在会标明已加密、读不到内容。

### 文档

- 官网补上实时分析的介绍（新章节、首屏文案与常见问题同步），请求详情一节加实际转发说明。
- 建站源码与工具回归主线目录，public/ 冻结快照里对应的副本下线，原始摘要保留可核验恢复。
- 披露断面开始分批下线：先删与主线逐字节一致的许可证副本和只差两处链接的构建手册，其余待内容复核。
- 变更记录改成三份：日常看的两份只用中文，发版给 GitHub 用的三语正文单独放一份，发版前对不上会直接挡住。
- 变更记录的写法要求收归开发入口文件一处，开发约定里那份互相打架的旧口径删掉。
- 变更记录顶部的状态卡从五节收成三节，不再抄当前版本的功能描述。

## English

### Added

- The capture page now has a collapsible "Cold storage" shelf: days you have not opened in a while are tucked away and squeezed down further, and one click thaws a day back onto the date bar.
- Settings can turn off automatic cold storage or change the threshold (7 days by default), and you can also freeze a single day by hand from the capture page.

### Changed

- The realtime-analysis page now uses six font sizes, so content at the same level no longer comes in a different size in every block.

### Fixed

- Opening a goal on the realtime-analysis page showed a number that did not match the card in the diagram, which made a single task read as the overall goal.
- Reasoning that the upstream had encrypted showed up blank in the capture detail view, indistinguishable from the model not having reasoned at all. It is now marked as encrypted and unreadable.

### Docs

- The website gained an introduction to realtime analysis (new section, hero copy and FAQ kept in sync), and the request-detail section now explains actual forwarding.
- Website source and tooling moved back to the mainline directories; the matching copies in the frozen public/ snapshot were retired, with the original digests kept so the removal stays verifiable.
- The disclosure snapshot is being retired in batches: first to go were the licence copies that were byte-identical to the mainline and a build handbook that differed only in two links; the rest await a content review.
- The changelog is now three files: the two you read day to day are Chinese-only, the trilingual text for GitHub releases lives on its own, and a mismatch blocks the release.
- The rules for writing the changelog were consolidated into the development entry file, and the conflicting older wording in the development conventions was deleted.
- The status card at the top of the changelog went from five sections to three, and no longer copies the current version's feature descriptions.

## 日本語

### 追加

- キャプチャ画面に「冷蔵済み」の折りたたみ領域を追加しました。しばらく開いていない日付は自動的にしまわれ、さらに圧縮されます。クリックすれば解凍されて日付バーに戻ります。
- 設定から自動冷蔵を無効にしたり日数を変更したりできます（既定は 7 日）。キャプチャ画面から特定の日を手動で冷蔵することもできます。

### 変更

- リアルタイム分析画面のフォントサイズを 6 段階に整理し、同じ階層の内容がブロックごとに違う大きさになることがなくなりました。

### 修正

- リアルタイム分析画面で目標を開くと、表示される番号が図中のカードと一致せず、1 つのタスクが全体目標として読まれてしまう問題を修正しました。
- 上流で暗号化された思考がキャプチャ詳細で空白として表示され、モデルがそもそも思考していない場合と区別できませんでした。現在は暗号化済みで内容が読めないことを明示します。

### ドキュメント

- 公式サイトにリアルタイム分析の紹介を追加しました（新しい節、ファーストビューの文言、FAQ を同期）。リクエスト詳細の節には実際の転送についての説明を追加しました。
- サイトのソースとツールを本流のディレクトリに戻し、凍結された public/ スナップショット内の該当コピーを撤去しました。検証できるよう元のダイジェストは残しています。
- 開示スナップショットの段階的な撤去を開始しました。まず本流とバイト単位で同一のライセンスコピーと、リンク 2 か所しか違わないビルド手引きを削除しました。残りは内容確認待ちです。
- 変更記録を 3 つのファイルに分けました。日常的に読む 2 つは日本語ではなく中国語のみ、GitHub リリース用の三言語の本文は独立させ、食い違いがあればリリースを止めます。
- 変更記録の書き方に関する規定を開発の入口ファイル 1 か所に集約し、開発規約側にあった矛盾する古い記述を削除しました。
- 変更記録冒頭のステータスカードを 5 節から 3 節に整理し、現行バージョンの機能説明を書き写すのをやめました。
