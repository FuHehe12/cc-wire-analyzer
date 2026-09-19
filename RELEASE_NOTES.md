<!--
tag: v0.4.43

这份文件只装一个版本：最近发布的那一版，或正在准备发布的那一版。发新版时整体覆盖，不累积历史。
GitHub Release 页的正文由 CI 从这里取（`-->` 之后到文件末尾原样发出），上面这行 tag 必须与本次
git tag 一致，不一致就发版失败——宁可红一次重发，也不能拿上一版的说明发出去。

为什么单独一份：根目录两份 CHANGELOG 只用中文（本地自己看），而 GitHub 发布要三语。
内容与 CHANGELOG.md 当前版本段一一对应，但不带 `（issue …）` 指针——`issues/` 不公开，
对站外读者是死链。写法口径见 CLAUDE.md 的「CHANGELOG 纪律」。
-->

## 中文

### 修复

- 输入框右键现在有粘贴、复制、全选菜单——此前 mac 无右键粘贴入口，长串配置只能靠快捷键。
- 在别的页面切换界面语言后回到分析页，快照占用行与对比结果不再是切换前的语言。
- 「压缩当天录制」等存储操作被拒绝时提示给出具体原因与指引，不再只有「操作失败」四个字。
- 录制代理转发时地址中的查询串（如 beta 标志）被丢弃，现原样透传并完整记录；客户端未声明压缩时不代它请求压缩，避免收到无法解开的乱码。
- mac 应用内更新换版成功后新窗口不出现、程序图标变白框，重启改经系统正常启动方式拉起新版本。
- mac 翻译与模型连通测试报证书错误，证书信任源改为全应用统一从打包内置清单获取，更新检查与翻译共用同一处。
- mac 程序图标在程序坞呈白色方框观感（启动后仍会被运行时图标盖回），图标资产与运行时图标统一按系统圆角规范裁形并留出透明边距。

## English

### Fixed

- Text inputs now have a right-click menu with paste, copy and select-all; previously macOS offered no right-click paste entry, leaving keyboard shortcuts as the only way to paste long strings.
- After switching the interface language on another page, the snapshot usage row and comparison results on the analysis page no longer stay in the previous language.
- When storage operations such as compacting today's recordings are rejected, the notice now states the specific reason and what to do, instead of a bare "operation failed".
- The recording proxy dropped the query string from forwarded addresses (such as beta flags); it now passes it through unchanged and records it in full, and no longer requests compression on behalf of clients that did not ask for it, avoiding undecodable responses.
- On macOS, after an in-app update the new window did not appear and the Dock icon turned into a white block; the restart now launches the new version through the system's normal launch mechanism.
- Translation and model connectivity tests on macOS reported certificate errors; the trust store is now loaded for the whole app from the bundled certificate list, shared by the update checker and translation.
- The macOS Dock icon read as a white block (and was overwritten by the runtime icon after launch); the icon asset and the runtime icon are now both shaped with the system rounded-corner mask and transparent margins.

## 日本語

### 修正

- 入力欄に右クリックメニュー（貼り付け・コピー・すべて選択）が加わりました。macOS では以前これがなく、長い設定文字列の貼り付けはショートカットキーしかありませんでした。
- 他のページで表示言語を切り替えた後、分析ページのスナップ占有行と比較結果が切り替え前の言語のまま残ることがなくなりました。
- 「当日の録画を圧縮」などのストレージ操作が拒否された際、具体的な理由と対処を示すようになりました。「操作に失敗」の一語だけではなくなります。
- 録画プロキシが転送アドレスのクエリ文字列（ベータフラグなど）を落とす問題を修正しました。クエリはそのまま透過して完全に記録し、圧縮を宣言していないクライアントの代わりに圧縮を要求しなくなったため、解読不能な応答を避けられます。
- macOS でアプリ内更新の置き換え後、新しいウィンドウが出ず Dock アイコンが白い枠になる問題を修正しました。再起動はシステムの通常の起動方法で新バージョンを立ち上げます。
- macOS で翻訳とモデル接続テストが証明書エラーになる問題を修正しました。信頼の供給源をパッケージ同梱の証明書リストからアプリ全体で統一して取得し、更新確認と翻訳で共有します。
- macOS の Dock アイコンが白い四角に見える問題（起動後は実行時アイコンで上書きされる）を修正しました。アイコン素材と実行時アイコンをシステムの角丸規定に合わせて整形し、透明の余白を確保しました。
