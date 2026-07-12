# CC Wire Analyzer

A local MITM proxy desktop app that transparently records and analyzes all HTTP traffic between **Claude Code** and its upstream endpoint — filling the wire-level gap that `~/.claude/projects/*.jsonl` (CC's post-processed view) and OTLP telemetry can't show.

[日本語](#日本語) · [中文](#中文)

## What it shows that you can't otherwise see

When Claude Code talks to an upstream (Anthropic official, or a third-party gateway), the outgoing requests hide link-level truth that jsonl/OTLP can't capture: the raw watermark fields in the system prompt, SSE chunk timing, the exact upstream response, security-classifier calls, precise token cost. This tool spins up a local proxy, temporarily points CC's `ANTHROPIC_BASE_URL` at it, and **records + forwards** everything — so those truths become observable.

## Screenshots

| Captures | Timeline DAG |
|---|---|
| ![Captures](docs/screenshots/en/view-a-captures.png) | ![Timeline](docs/screenshots/en/view-d-dag.png) |

| Request detail | Settings |
|---|---|
| ![Detail](docs/screenshots/en/view-b-detail.png) | ![Settings](docs/screenshots/en/view-c-settings.png) |

## Features

- **Zero intrusion** — only edits `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`; token, model mapping, OTLP config all preserved. Closing the app byte-restores the file.
- **Works with official-direct and third-party endpoints** — no `ANTHROPIC_BASE_URL` (direct to Anthropic) works too, falling back to capture the official endpoint; if present, follows it (e.g. a gateway configured via [cc-switch](https://github.com/farion1231/cc-switch)).
- **Transparent streaming** — SSE is forwarded while recorded; CC feels identical to a direct connection.
- **Crash protection** — atomic writes + per-start backup + atexit/signal/excepthook triple restore + orphan-backup recovery.
- **Timeline DAG** — swimlane view; each main session gets its own color across the lane header, axis, node border, and edges; subagent/auxiliary nodes carry a dot in their related session's color so you can see what spawned what at a glance.
- **Detail tools** — translate, "ask AI what this does" (with prompt-injection guard), format/pretty-print; UI supports **Chinese / English / Japanese** switch (instant, persisted).
- **Clear recordings** — clear a day's captures (direct delete / archive-to-zip then delete), with inline two-step confirm.
- **Cross-platform** — Windows `.exe` and macOS `.app`, built via GitHub Actions. **Fonts are bundled** (Inter + JetBrains Mono + Noto Sans SC) so the UI looks identical on every machine.

## Quick start

### Option A — download a release build

Grab the latest `cc-wire-analyzer-windows.exe` or `CCWireAnalyzer-mac.zip` from [Releases](../../releases). No Python needed.

- **Windows**: double-click the `.exe`. If it warns about WebView2 missing, install [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- **macOS**: unzip, drag `CCWireAnalyzer.app` to `/Applications`. First launch, right-click → Open (the app is unsigned, so Gatekeeper will prompt).

### Option B — run from source

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS (installs pyobjc)
uv run python src/desktop.py
```

Then click **Start proxy** in the app, open a new Claude Code session, use it normally — traffic appears in the captures list.

## How it works (the 30-second version)

1. You click **Start proxy**.
2. The app backs up `~/.claude/settings.json`, then sets `ANTHROPIC_BASE_URL` to `http://127.0.0.1:<port>` (one field, nothing else touched).
3. Claude Code now sends all requests to the local proxy, which records (JSONL, headers redacted) and forwards them to the real upstream.
4. You click **Stop proxy** (or close the app) → `ANTHROPIC_BASE_URL` is restored byte-for-byte.

While the proxy runs, **don't switch endpoints with cc-switch** — it rewrites `BASE_URL` and CC would bypass the proxy.

## Data location

| Path | Content |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | Request/response recordings (append-only) |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | Archived recordings (when you "archive then clear") |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json backups (keeps last 5) |
| `~/.cc-wire-analyzer/config.json` | App config (ui_lang / translate / explain …) |
| `~/.cc-wire-analyzer/run.log` | Run log |

## Optional: translate / ask-AI

The detail page can translate text or explain "what does this content do" via any OpenAI-compatible `/chat/completions` endpoint. Configure API key / base URL / model in **Settings → LLM model**. The explain feature has a built-in injection guard (the untrusted captured content is wrapped in delimiters; literal closing tags are escaped; the isolation frame is hardcoded and unaffected by your custom prompt).

## Build from source

- **Windows**: `uv run pyinstaller build.spec`
- **macOS**: `uv sync --extra mac && uv run pyinstaller build-mac.spec`

Releases are built automatically by [`.github/workflows/release.yml`](.github/workflows/release.yml) on every `v*` tag.

## Relationship to other observability tools

This tool covers the **wire level** (raw HTTP). It pairs well with jsonl-based conversation analyzers (CC's own view) and OTLP telemetry (metrics view) — the three are complementary.

## License

- Code: **MIT**.
- Documentation and prose (README / docs / in-app text): **CC BY 4.0** — credit the source if you reuse it.
- Bundled fonts (Inter / JetBrains Mono / Noto Sans SC): **SIL OFL 1.1**.
- Bundled JS (marked.js: MIT; DOMPurify: Apache-2.0/MPL-2.0).

Full text in [LICENSE](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup.

---

## 中文

本地 MITM 代理桌面应用，透明转发并**完整录制** Claude Code ↔ 上游端点的全部 HTTP 流量——填补 `~/.claude/projects/*.jsonl`（CC 的已加工视图）和 OTLP 遥测都看不到的链路级维度。

### 它能让你看到原本看不到的东西

Claude Code 与上游（Anthropic 官方或第三方网关）通信时，发出的请求里藏着 jsonl/OTLP 抓不到的链路级真相：system prompt 里原始的水印字段、SSE 分块时序、上游的确切响应、安全分类器调用、精确的 token 成本。本工具起一个本地代理，临时把 CC 的 `ANTHROPIC_BASE_URL` 指向它，**边录制边转发**全部流量——让这些真相变得可观测。

### 截图

| 捕获列表 | 时序 DAG |
|---|---|
| ![Captures](docs/screenshots/zh/view-a-captures.png) | ![Timeline](docs/screenshots/zh/view-d-dag.png) |

| 请求详情 | 设置 |
|---|---|
| ![Detail](docs/screenshots/zh/view-b-detail.png) | ![Settings](docs/screenshots/zh/view-c-settings.png) |

### 特性

- **零侵入** —— 只改 `~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL`，token、模型映射、OTLP 配置全保留。关闭软件时字节级复原该文件。
- **官方直连与第三方端点都支持** —— 没有 `ANTHROPIC_BASE_URL`（直连 Anthropic）也能用，自动回退抓官方端点；有则跟随（例如用 [cc-switch](https://github.com/farion1231/cc-switch) 配的网关）。
- **透明流式** —— SSE 边转发边录制，CC 用起来和直连完全一样。
- **崩溃保护** —— 原子写 + 每次启动备份 + atexit/signal/excepthook 三重恢复 + 孤儿备份恢复。
- **时序 DAG** —— 泳道视图；每条主线会话在泳道头、轴线、节点边框、连线上都用各自颜色；子代理/辅助节点带关联主线颜色的点，一眼看出谁派生了谁。
- **详情工具** —— 翻译、"问 AI 这是什么意思"（带提示词注入防护）、格式化/美化；界面支持**中文/英文/日文**切换（即时、持久化）。
- **清理录制** —— 清掉某天的捕获（直接删除 / 压缩存档后删除），内联二次确认。
- **跨平台** —— Windows `.exe` 和 macOS `.app`，由 GitHub Actions 构建。**字体全打包**（Inter + JetBrains Mono + Noto Sans SC），每台机器上界面都长得一样。

### 快速开始

#### 方式 A —— 下载 release 构建

从 [Releases](../../releases) 下载最新的 `cc-wire-analyzer-windows.exe` 或 `CCWireAnalyzer-mac.zip`。不需要 Python。

- **Windows**：双击 `.exe`。如果提示 WebView2 缺失，装一下 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
- **macOS**：解压，把 `CCWireAnalyzer.app` 拖到 `/Applications`。首次启动右键 → 打开（应用未签名，Gatekeeper 会提示）。

#### 方式 B —— 源码运行

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS（装 pyobjc）
uv run python src/desktop.py
```

然后在软件里点**启动代理**，新开一个 Claude Code 会话，正常使用——流量就出现在捕获列表里。

### 工作原理（30 秒版）

1. 你点**启动代理**。
2. 软件备份 `~/.claude/settings.json`，然后把 `ANTHROPIC_BASE_URL` 设成 `http://127.0.0.1:<端口>`（只这一字段，其他不动）。
3. Claude Code 此后所有请求都发给本地代理，代理录制（JSONL，headers 脱敏）并转发给真正的上游。
4. 你点**停止代理**（或关闭软件）→ `ANTHROPIC_BASE_URL` 字节级复原。

代理运行期间，**不要用 cc-switch 切换端点** —— 它会重写 `BASE_URL`，CC 就绕过代理了。

### 数据位置

| 路径 | 内容 |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | 请求/响应录制（只追加） |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | 归档录制（选"压缩存档后删除"时） |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json 备份（留最近 5 份） |
| `~/.cc-wire-analyzer/config.json` | 应用配置（ui_lang / translate / explain…） |
| `~/.cc-wire-analyzer/run.log` | 运行日志 |

### 可选：翻译 / 问 AI

详情页可以通过任何 OpenAI 兼容的 `/chat/completions` 端点翻译文本或解读"这段内容在干什么"。在**设置 → LLM 模型**里配 API key / base URL / model。解读功能内置注入防护（不可信的捕获内容被定界符包裹；字面闭合标签被转义；隔离框架是硬编码的，不受你的自定义提示词影响）。

### 源码构建

- **Windows**：`uv run pyinstaller build.spec`
- **macOS**：`uv sync --extra mac && uv run pyinstaller build-mac.spec`

Release 由 [`.github/workflows/release.yml`](.github/workflows/release.yml) 在每个 `v*` tag 上自动构建。

### 和其他可观测性工具的关系

本工具覆盖**链路层**（原始 HTTP）。它和基于 jsonl 的对话分析器（CC 自己的视图）、OTLP 遥测（指标视图）配合得很好——三者互补。

### 许可证

- 代码：**MIT**。
- 文档与文字（README / docs / 界内文字）：**CC BY 4.0** —— 复用时请注明出处。
- 打包字体（Inter / JetBrains Mono / Noto Sans SC）：**SIL OFL 1.1**。
- 打包 JS（marked.js：MIT；DOMPurify：Apache-2.0/MPL-2.0）。

全文见 [LICENSE](LICENSE)（英文）。API 契约等技术文档见 [docs/API契约.md](docs/API契约.md)（中文）。

---

## 日本語

Claude Code と上流エンドポイント間の全 HTTP トラフィックを透過的に**完全録画**するローカル MITM プロキシのデスクトップアプリ——`~/.claude/projects/*.jsonl`（CC の後処理済みビュー）や OTLP テレメトリでは見えないリンクレベルの次元を補います。

### 他では見えないものが見える

Claude Code が上流（Anthropic 公式またはサードパーティのゲートウェイ）と通信する際、送出リクエストには jsonl/OTLP では捕捉できないリンクレベルの真実が隠れています：システムプロンプト内の生のウォーターマークフィールド、SSE チャンクのタイミング、上流の正確なレスポンス、セキュリティ分類器の呼び出し、正確なトークンコスト。本ツールはローカルプロキシを立ち上げ、CC の `ANTHROPIC_BASE_URL` を一時的にそこへ向け、全トラフィックを**録画しながら転送**します——これらの真実を観測可能にします。

### スクリーンショット

| キャプチャ一覧 | タイムライン DAG |
|---|---|
| ![Captures](docs/screenshots/ja/view-a-captures.png) | ![Timeline](docs/screenshots/ja/view-d-dag.png) |

| リクエスト詳細 | 設定 |
|---|---|
| ![Detail](docs/screenshots/ja/view-b-detail.png) | ![Settings](docs/screenshots/ja/view-c-settings.png) |

### 主な機能

- **非侵入** —— `~/.claude/settings.json` の `ANTHROPIC_BASE_URL` だけを編集。トークン、モデルマッピング、OTLP 設定は全保持。アプリ終了時にバイト級で復元します。
- **公式直通・サードパーティ両対応** —— `ANTHROPIC_BASE_URL` なし（Anthropic へ直通）でも動作、公式エンドポイントのキャプチャにフォールバック。設定されていればそれに従います（例：[cc-switch](https://github.com/farion1231/cc-switch) で設定したゲートウェイ）。
- **透過ストリーミング** —— SSE を録画しながら転送。CC にとって直通と全く同じ感覚です。
- **クラッシュ保護** —— 原子書き込み + 起動ごとのバックアップ + atexit/signal/excepthook の三重復元 + 孤児バックアップ復元。
- **タイムライン DAG** —— スイムレーンビュー。各メインセッションはレーンヘッダー、軸、ノード枠線、エッジに独自の色を持ちます。サブエージェント/補助ノードは関連セッションの色の点を持ち、何が何を派生したかが一目で分かります。
- **詳細ツール** —— 翻訳、「これが何を意味するか AI に聞く」（プロンプト注入ガード付き）、整形/プリティプリント。UI は**中国語/英語/日本語**切り替え対応（即時・永続化）。
- **録画クリア** —— その日のキャプチャを消去（直接削除 / zip 書庫化してから削除）、インライン二段階確認付き。
- **クロスプラットフォーム** —— Windows `.exe` と macOS `.app`、GitHub Actions でビルド。**フォント同梱**（Inter + JetBrains Mono + Noto Sans SC）で、どのマシンでも同じ見た目。

### クイックスタート

#### 方法 A —— リリースビルドをダウンロード

[Releases](../../releases) から最新の `cc-wire-analyzer-windows.exe` または `CCWireAnalyzer-mac.zip` を取得。Python は不要。

- **Windows**：`.exe` をダブルクリック。WebView2 不足を警告されたら [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) をインストール。
- **macOS**：解凍し、`CCWireAnalyzer.app` を `/Applications` にドラッグ。初回起動は右クリック → 開く（アプリは未署名なので Gatekeeper がプロンプトします）。

#### 方法 B —— ソースから実行

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS（pyobjc をインストール）
uv run python src/desktop.py
```

アプリ内で**プロキシ開始**をクリックし、新しい Claude Code セッションを開いて普通に使う——トラフィックがキャプチャ一覧に現れます。

### 仕組み（30 秒版）

1. **プロキシ開始**をクリック。
2. アプリが `~/.claude/settings.json` をバックアップし、`ANTHROPIC_BASE_URL` を `http://127.0.0.1:<ポート>` に設定（この一フィールドだけ、他は触らない）。
3. Claude Code の全リクエストがローカルプロキシに送られ、プロキシは録画（JSONL、ヘッダーはマスク）しながら本当の上流へ転送。
4. **プロキシ停止**（またはアプリ終了）→ `ANTHROPIC_BASE_URL` がバイト級で復元。

プロキシ実行中は **cc-switch でエンドポイントを切り替えないで**——`BASE_URL` を書き換えるため CC がプロキシをバイパスします。

### データ位置

| パス | 内容 |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | リクエスト/レスポンス録画（追記専用） |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | 書庫化録画（「zip 書庫化してから削除」時） |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json バックアップ（直近 5 件保持） |
| `~/.cc-wire-analyzer/config.json` | アプリ設定（ui_lang / translate / explain…） |
| `~/.cc-wire-analyzer/run.log` | 実行ログ |

### オプション：翻訳 / AI に聞く

詳細ページは、OpenAI 互換の `/chat/completions` エンドポイント経由でテキスト翻訳や「この内容が何をするものか」解説ができます。**設定 → LLM モデル**で API キー / base URL / model を設定。解説機能には組み込みの注入ガードがあります（信頼できないキャプチャ内容はデリミタで包まれ、リテラルの閉じタグはエスケープされ、隔離フレームはハードコードされておりカスタムプロンプトの影響を受けません）。

### ソースからビルド

- **Windows**：`uv run pyinstaller build.spec`
- **macOS**：`uv sync --extra mac && uv run pyinstaller build-mac.spec`

リリースは [`.github/workflows/release.yml`](.github/workflows/release.yml) が各 `v*` タグで自動ビルドします。

### 他の観測性ツールとの関係

本ツールは**リンクレベル**（生 HTTP）をカバー。jsonl ベースの会話アナライザ（CC 自身のビュー）や OTLP テレメトリ（メトリクスビュー）と相性が良い——三者は補完的。

### ライセンス

- コード：**MIT**。
- ドキュメントと文章（README / docs / アプリ内テキスト）：**CC BY 4.0** —— 再利用時は出典を明記。
- 同梱フォント（Inter / JetBrains Mono / Noto Sans SC）：**SIL OFL 1.1**。
- 同梱 JS（marked.js：MIT、DOMPurify：Apache-2.0/MPL-2.0）。

全文は [LICENSE](LICENSE)（英語）を参照。
