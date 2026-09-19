<!--
tag: v0.4.41

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 变更

- mac 检查更新后与 Windows 一样点一下完成换版并重启，替换不了（无写权限、非标准安装位置）时仍指路访达由用户手动拖入。经浏览器下载安装的 mac 用户请把应用拖入「应用程序」一次：系统会隔离运行这类下载来的应用，拖入前点一下换版会退回手动模式。

### 修复

- mac 下载更新后解出的新版本无法启动，改用与打包同一套系统工具解压以完整还原包内链接与权限，解压失败时如实报错。

## English

### Changed

- On macOS, checking for updates now finishes the swap with one click and restarts, same as on Windows; when replacement is not possible (no write permission, non-standard install location) it still points you to Finder for a manual drag-in. If you originally installed via a browser download, drag the app into Applications once: macOS runs such apps from an isolated location, and until then one-click replacement falls back to manual mode.

### Fixed

- On macOS the newly downloaded version failed to launch after an update; extraction now uses the same system tool as packaging to fully restore the links and permissions inside the archive, and extraction failures are reported honestly.

## 日本語

### 変更

- macOS でも、更新確認後は Windows と同じくワンクリックで置き換えて再起動します。置き換えられない場合（書き込み権限がない、標準外の場所へのインストール）は、引き続き Finder を示して手動でのドラッグ入れを案内します。ブラウザ経由でダウンロード・インストールした場合は、アプリを「アプリケーション」へ一度ドラッグしてください。macOS はこの種のアプリを隔離された場所で実行するため、ドラッグまでワンクリック置き換えは手動モードに戻ります。

### 修正

- macOS で更新ダウンロード後の新バージョンが起動しない問題を修正しました。パッケージ作成と同じシステムツールで解凍し、アーカイブ内のリンクと権限を完全に復元します。解凍に失敗した場合は正直にエラーを報告します。
