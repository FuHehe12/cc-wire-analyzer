<!--
tag: v0.4.39

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 新增

- 顶栏多了「详情」一格：看某条请求时切去时序或设置，点它就切回刚才那条，之前点出来的翻译和 AI 解读都还在，不用重来一遍。

### 变更

- 捕获详情页里加密思考那段说明收成一句话，不再占两行。

### 修复

- mac 安装包每次启动都要现场解包并逐个校验几十个组件，双击到界面出现约需 6 秒，改为安装时就放好后，热启动约 0.6 秒、体积不变。
- mac 安装包里没有受信任的根证书，点「检查更新」永远报证书校验失败，现在随包带上并用它连 GitHub。
- 极快连续创建快照时列表排序在两条读取路径上不一致，发版自检因此偶发失败，现在排序确定一致、不再偶发。
- 部分上游会显式声明内容未压缩，此前被误当成解码失败计进错误统计，现在按正常响应对待。
- 命令行敲了不存在的子命令时，此前一声不吭弹出图形界面把命令挂住，现在报错并退出。
- 快照对比两段完全相同时不再显示「正文差异」区块，不会再把相同行误读成一处差异。
- 程序抛出没接住的错误时，终端里不再只剩一个退出码，报错内容会照常打出来。
- 白板上会凭空多出一模一样的贴纸，批量清理碰到它们还会报删除失败，现在两件事都不再发生。
- 拖动一张贴纸和整理整块白板越来越慢，慢的程度跟着快照总量涨，现在与快照堆了多少无关。
- 备份、拖动、删除、整理、批量清理期间界面毫无动静，现在右下角会转圈说明在做什么、整理到第几张。
- 连点「备份当前录制」会真存下好几份一样的快照，现在一次备份没结束前的重复点击不再重复保存。
- 贴纸位置没存上时界面一声不吭、下次打开又回原处，现在会说明失败并把贴纸放回原位。
- 快照占用把分析结果也数成了快照，张数比白板上多；删快照时留下的旧语义分析文件现在也一并清掉。

## English

### Added

- The top bar gained a "Detail" tab: while reading a request you can switch to the timeline or settings and click it to come straight back to that same request, with the translations and AI explanations you had already pulled up still there.

### Changed

- The note about encrypted reasoning in the capture detail view was shortened to a single line instead of two.

### Fixed

- The macOS build unpacked itself and verified dozens of components on every launch, taking about 6 seconds from double-click to window; the files are now put in place at install time, so a warm start takes about 0.6 seconds at the same download size.
- The macOS build shipped without trusted root certificates, so "Check for updates" always failed certificate validation; it now carries them and uses them to reach GitHub.
- Creating snapshots in very quick succession ordered the list differently along two read paths, which made the release self-check fail intermittently; the order is now deterministic and the flake is gone.
- Some upstreams explicitly declare content as uncompressed, which used to be counted as a decode failure in the error statistics; such responses are now treated as normal.
- Typing a subcommand that does not exist used to silently open the GUI and hang the command; it now reports the error and exits.
- Snapshot comparison no longer shows a "body differences" block when the two texts are identical, so identical lines are no longer read as a difference.
- When the program raises an uncaught error, the terminal no longer shows just an exit code — the traceback is printed as usual.
- Duplicate stickies appeared on the board out of nowhere, and bulk cleanup then failed to delete them; neither happens any more.
- Dragging a single sticky and tidying the whole board got slower as the snapshot count grew; both are now independent of how many snapshots have piled up.
- Backup, drag, delete, tidy and bulk cleanup gave no sign of progress; a spinner in the bottom right now says what is running and how far along the tidy is.
- Clicking "Back up current recording" repeatedly really did store several identical snapshots; repeat clicks before a backup finishes no longer save again.
- When a sticky's position failed to save, the interface said nothing and the sticky was back where it started next time; it now reports the failure and puts the sticky back.
- Snapshot disk usage counted analysis results as snapshots, giving a higher count than the board showed; deleting a snapshot now also removes the stale semantic-analysis files it used to leave behind.

## 日本語

### 追加

- 上部バーに「詳細」タブを追加しました。あるリクエストを読んでいる途中でタイムラインや設定に切り替えても、このタブを押せばそのリクエストにそのまま戻れます。すでに実行した翻訳や AI 解説の結果も残ったままです。

### 変更

- キャプチャ詳細にある暗号化された思考についての説明を、2 行から 1 行に短縮しました。

### 修正

- macOS 版は起動のたびに自身を展開して数十個のコンポーネントを検証しており、ダブルクリックから画面表示まで約 6 秒かかっていました。インストール時に配置する方式に変更し、ウォーム起動は約 0.6 秒、サイズは変わりません。
- macOS 版に信頼されたルート証明書が同梱されておらず、「更新を確認」が常に証明書検証エラーになっていました。現在は同梱し、それを使って GitHub に接続します。
- 極めて短い間隔でスナップショットを作成すると、2 つの読み取り経路で一覧の並び順が食い違い、リリース時の自己点検がまれに失敗していました。並び順が確定的になり、この揺らぎはなくなりました。
- 一部の上流は内容が非圧縮であることを明示します。これまではデコード失敗としてエラー統計に数えていましたが、正常な応答として扱うようにしました。
- 存在しないサブコマンドを入力すると、何も言わずに GUI が開いてコマンドが返らなくなっていました。現在はエラーを表示して終了します。
- スナップショット比較で 2 つの本文が完全に同一の場合、「本文の差分」ブロックを表示しなくなりました。同一の行が差分として読まれることはもうありません。
- 捕捉されない例外が発生したとき、ターミナルに終了コードしか残らないことがなくなり、エラー内容が通常どおり出力されます。
- ボード上に同一の付箋が勝手に増え、一括整理がそれらの削除に失敗していました。どちらも発生しなくなりました。
- 付箋 1 枚のドラッグとボード全体の整理が、スナップショットの総数に比例して遅くなっていました。現在は蓄積量に依存しません。
- バックアップ・ドラッグ・削除・整理・一括削除の実行中に画面が無反応でした。現在は右下のスピナーが実行中の処理と整理の進捗を表示します。
- 「現在の記録をバックアップ」を連打すると同じスナップショットが複数保存されていました。1 回のバックアップが終わるまでの重複クリックでは保存されません。
- 付箋の位置の保存に失敗しても画面は何も言わず、次に開くと元の位置に戻っていました。現在は失敗を伝え、付箋を元の位置に戻します。
- スナップショットの使用量が分析結果もスナップショットとして数えており、ボードの表示より枚数が多くなっていました。スナップショット削除時に残っていた古い意味解析ファイルも併せて削除します。
