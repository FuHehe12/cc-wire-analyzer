# CC Wire Analyzer

Claude Code と上流エンドポイント間の全 HTTP トラフィックを透過的に**完全録画**するローカル MITM プロキシのデスクトップアプリ——`~/.claude/projects/*.jsonl`（CC の後処理済みビュー）や OTLP テレメトリでは見えないリンクレベルの次元を補います。

[English](README.md) · [中文](README.zh.md)

[リリース一覧](../../releases) · [変更履歴](CHANGELOG.md)

> 初めての方へ（ドキュメントはすべて中国語）：
> **[docs/界面导览.md](docs/界面导览.md)** — UI で人が見るもの ·
> **[docs/报文解读.md](docs/报文解读.md)** — Claude Code が実際に送っているもの ·
> **[docs/AI_USAGE.md](docs/AI_USAGE.md)** — 本ツールを操作する AI エージェント向け ·
> **[docs/架构总览.md](docs/架构总览.md)** — アプリの構成 ·
> **[docs/开发指南.md](docs/开发指南.md)** — コードを変更する前に必読 ·
> **[docs/问题域手册.md](docs/问题域手册.md)** — 別のエージェント基盤で同種のツールを作る場合 ·
> **[docs/文档维护策略.md](docs/文档维护策略.md)** — これらの文書の同期を保つ方法。
> *（詳細ドキュメントは中国語です。必要なら機械翻訳を。）*

## こんなときに使う

Claude Code が見せるのは、CC 自身の視点から見たセッションです。wire レイヤーが見せるのは、実際に何が送られ、実際に何が返ってきたか——この二つは同じものではありません。wire が必要になるのは、たとえば次のようなときです：

- **CC がサードパーティのゲートウェイ経由で、どこかがおかしい。** リクエストが失敗する、モデルの返答が想定と違う、コストが合わない——それでも CC の画面は「何かが起きた」としか教えてくれません。上流の実際のレスポンス（エラーメッセージを含む）は wire レイヤーにあります。
- **CC が実際に何を送っているのか確かめたい。** 送信されたままのシステムプロンプト全文（ウォーターマークフィールドも含む）、どのリクエストでどのツールが宣言されたか、サブエージェントがいつどんなプロンプトで派生したか、目に触れることのないバックグラウンドのセキュリティ分類器呼び出し、SSE チャンクのタイミング、そして上流が報告したままのトークン数——後から要約されたものではなく。
- **セッションを記録として残したい。** すべてローカルのプレーンな JSONL に書き出されるので、後から自分で（あるいは別のエージェントが HTTP API 経由で）遡って調べられます。問題を再現しようと苦労する必要はありません。

**たぶん不要な方**：公式エンドポイントを使っていて、特に問題も起きておらず、会話履歴が見たいだけなら——`~/.claude/projects/*.jsonl` に既にありますし、そちらの方が読みやすいです。本ツールの出番は、問いが「実際に線の上を何が流れたのか」に変わったときです。

## スクリーンショット

| キャプチャ一覧 | タイムライン DAG |
|---|---|
| ![Captures](docs/screenshots/ja/view-a-captures.png) | ![Timeline](docs/screenshots/ja/view-d-dag.png) |

| リクエスト詳細 | 設定 |
|---|---|
| ![Detail](docs/screenshots/ja/view-b-detail.png) | ![Settings](docs/screenshots/ja/view-c-settings.png) |

## 実例：静かに失敗し続けていたセッションタイトル

メンテナ自身のマシンでの録画です。セッションタイトルが生成されなくなっていましたが、Claude Code はエラーを一切表示しません——タイトルがただ出てこないだけで、気づくことすら難しい状態でした。

録画では title リクエストがすべて `400` を返しており、上流は理由をすでに説明していました：

```
output_config.effort 'max' is not supported when thinking is disabled on this model.
Use effort 'high' or below, or enable thinking.
```

原因は設定の矛盾でした：`settings.json` のトップレベルに `effortLevel: low`、一方で環境変数に `CLAUDE_CODE_EFFORT_LEVEL: max` があり、環境変数が優先されていたのです。CC 自身のビューには何の手がかりもなく、失敗していたリクエストは wire レイヤーでしか見えませんでした。

この発見はそのまま内蔵の**設定ヘルスチェック**の 2 つのルールになりました。同じ矛盾は今後、プロキシを起動する前に指摘されます——偶然見つかるのを待つのではなく。これが本ツールの狙うループです：上流がすでに一度診断している失敗を、まず可視化し、次にチェックとして固定する。何かを自動で直したりはしません——何が起きたかを見せ、どのフィールドが問題なのかを指し示します。

## トラフィックを預けて安全か

MITM プロキシを名乗るものに対して、当然聞くべき問いです。正直に答えると、4 点あります：

- **録画がマシンの外に出ることはありません。** 録画は `~/.cc-wire-analyzer/` にプレーンな JSONL として書き出され、トラフィックは CC が元々使っていた上流にそのまま転送されます。テレメトリもアカウントもアップロードもありません。本アプリ自身の外部通信は 2 つだけで、どちらもクリックしたときのみ発生します：詳細ビューの任意機能である翻訳 / AI 解説（選択した内容を**あなたが**設定したエンドポイントへ送信）と、情報パネルの「更新を確認」（api.github.com に最新リリースの tag を問い合わせるだけで、あなたに関する情報は送りません）。
- **触るのは設定 1 フィールド、終了時に復元。** プロキシが編集するのは `~/.claude/settings.json` の `ANTHROPIC_BASE_URL` のみで、それ以外——トークン、モデルマッピング、OTLP 設定——には手を触れません。編集前にバックアップを取り、復元はウィンドウの closing イベント・`atexit`・シグナル・起動時の孤児チェックに紐づけられ、最後の手段として `restore` コマンドもあります。復元されるのは「自分がやったと今も証明できる変更」だけです——その間にあなたや cc-switch が `BASE_URL` を変えていた場合、ファイルには触れません。
- **認証情報はマスクされますが、メッセージ内容はされません。** `Authorization` などのヘッダーはマスクして保存されます。一方でリクエスト／レスポンスの body は**そのまま**保存されます——それこそが本ツールの目的ですが、つまり録画にはあなたのプロンプト、セッションに引用されたファイルの中身、システムプロンプト全文が含まれます。capture ファイルは機微データとして扱ってください：中身を確認せずにチャットに貼ったり、バグ報告に添付したりしないでください。
- **既存の構成と共存します。** 公式エンドポイント直結、サードパーティのゲートウェイ、cc-switch——いずれも対応します。ただしプロキシの稼働中に cc-switch でエンドポイントを切り替えないでください：`BASE_URL` が書き換えられ、CC がプロキシを迂回します。本アプリはこれを監視していて、起きた場合には通知します。

## 主な機能

- **非侵入** —— `~/.claude/settings.json` の `ANTHROPIC_BASE_URL` だけを編集。トークン、モデルマッピング、OTLP 設定は全保持。アプリ終了時にバイト級で復元します。
- **公式直通・サードパーティ両対応** —— `ANTHROPIC_BASE_URL` なし（Anthropic へ直通）でも動作、公式エンドポイントのキャプチャにフォールバック。設定されていればそれに従います（例：[cc-switch](https://github.com/farion1231/cc-switch) で設定したゲートウェイ）。
- **透過ストリーミング** —— SSE を録画しながら転送。CC にとって直通と全く同じ感覚です。
- **クラッシュ保護** —— 原子書き込み + 起動ごとのバックアップ + atexit/signal/excepthook の三重復元 + 孤児バックアップ復元。
- **タイムライン DAG** —— スイムレーンビュー。各メインセッションはレーンヘッダー、軸、ノード枠線、エッジに独自の色を持ちます。サブエージェント/補助ノードは関連セッションの色の点を持ち、何が何を派生したかが一目で分かります。
- **詳細ツール** —— 翻訳、「これが何を意味するか AI に聞く」（プロンプト注入ガード付き）、整形/プリティプリント。UI は**中国語/英語/日本語**切り替え対応（即時・永続化）。
- **録画クリア** —— その日のキャプチャを消去（直接削除 / zip 書庫化してから削除）、インライン二段階確認付き。
- **クロスプラットフォーム** —— Windows `.exe` と macOS `.app`、GitHub Actions でビルド。**フォント同梱**（Inter + JetBrains Mono + Noto Sans SC）で、どのマシンでも同じ見た目。

## クイックスタート

### 方法 A —— リリースビルドをダウンロード

[Releases](../../releases) から最新の `cc-wire-analyzer-windows.exe` または `CCWireAnalyzer-mac.zip` を取得。Python は不要。

- **Windows**：`.exe` をダブルクリック。WebView2 不足を警告されたら [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) をインストール。
- **macOS**：解凍し、`CCWireAnalyzer.app` を `/Applications` にドラッグ。アプリは**未署名・未公証**（無料 OSS プロジェクトの標準——署名は年 $99 かかります）のため、**初回起動は Gatekeeper にブロックされます**。一度だけ許可してください：
  - `CCWireAnalyzer.app` を右クリック →「開く」→ダイアログで「開く」を確認、**または**
  - 新しい macOS で上記が出ない場合：**システム設定 → プライバシーとセキュリティ → 下部の「このまま開く」**をクリック。
  - 初回許可後は通常通り開き、以降プロンプトは出ません。（Apple のセキュリティ措置であり、アプリの不具合ではありません。）

### 方法 B —— ソースから実行

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS（pyobjc をインストール）
uv run python src/desktop.py
```

アプリ内で**プロキシ開始**をクリックし、新しい Claude Code セッションを開いて普通に使う——トラフィックがキャプチャ一覧に現れます。

## 仕組み（30 秒版）

1. **プロキシ開始**をクリック。
2. アプリが `~/.claude/settings.json` をバックアップし、`ANTHROPIC_BASE_URL` を `http://127.0.0.1:<ポート>` に設定（この一フィールドだけ、他は触らない）。
3. Claude Code の全リクエストがローカルプロキシに送られ、プロキシは録画（JSONL、ヘッダーはマスク）しながら本当の上流へ転送。
4. **プロキシ停止**（またはアプリ終了）→ `ANTHROPIC_BASE_URL` がバイト級で復元。

プロキシ実行中は **cc-switch でエンドポイントを切り替えないで**——`BASE_URL` を書き換えるため CC がプロキシをバイパスします。

## データ位置

| パス | 内容 |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | リクエスト/レスポンス録画（追記専用） |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | 書庫化録画（「zip 書庫化してから削除」時） |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json バックアップ（直近 5 件保持） |
| `~/.cc-wire-analyzer/config.json` | アプリ設定（ui_lang / translate / explain…） |
| `~/.cc-wire-analyzer/run.log` | 実行ログ |

## AI エージェント向け：HTTP で操作する

このツールは人が見るためだけのものではありません —— **エージェント自身が起動し、調べられます**。
バイナリ 1 つ、2 つのモード：

- `cc-wire-analyzer.exe`（ダブルクリック）→ GUI を開く
- `cc-wire-analyzer.exe serve` → **バックグラウンド HTTP サービス + プロキシ**を起動（ウィンドウなし、エージェント用）

`127.0.0.1` の HTTP で操作します（GUI と同じエンドポイント）：

```bash
cc-wire-analyzer.exe serve &                     # サービス + プロキシ起動（settings.json を patch）
port=$(cat ~/.cc-wire-analyzer/port.txt)
curl 127.0.0.1:$port/api/proxy/status            # 記録中か？
# …記録したいセッションを実行…
curl -X POST 127.0.0.1:$port/api/proxy/stop
curl "127.0.0.1:$port/api/captures?date=2026-07-13"
```

1 件の記録が 5 MB を超えることがあるため、まず概要を取得し id で個別取得します。
API 全一覧・レコード schema・安全上の注意は **[docs/AI_USAGE.md](docs/AI_USAGE.md)**。

macOS も同じバイナリ 1 つ —— `CCWireAnalyzer.app/Contents/MacOS/CCWireAnalyzer serve`。

## オプション：翻訳 / AI に聞く

詳細ページは、OpenAI 互換の `/chat/completions` エンドポイント経由でテキスト翻訳や「この内容が何をするものか」解説ができます。**設定 → LLM モデル**で API キー / base URL / model を設定。解説機能には組み込みの注入ガードがあります（信頼できないキャプチャ内容はデリミタで包まれ、リテラルの閉じタグはエスケープされ、隔離フレームはハードコードされておりカスタムプロンプトの影響を受けません）。

## ソースからビルド

- **Windows**：`uv run pyinstaller build.spec`
- **macOS**：`uv sync --extra mac && uv run pyinstaller build-mac.spec`

リリースは [`.github/workflows/release.yml`](.github/workflows/release.yml) が各 `v*` タグで自動ビルドします。

## 他の観測性ツールとの関係

本ツールは**リンクレベル**（生 HTTP）をカバー。jsonl ベースの会話アナライザ（CC 自身のビュー）や OTLP テレメトリ（メトリクスビュー）と相性が良い——三者は補完的。

## ライセンス

- コード：**MIT**。
- ドキュメントと文章（README / docs / アプリ内テキスト）：**CC BY 4.0** —— 再利用時は出典を明記。
- 同梱フォント（Inter / JetBrains Mono / Noto Sans SC）：**SIL OFL 1.1**。
- 同梱 JS（marked.js：MIT、DOMPurify：Apache-2.0/MPL-2.0）。

全文は [LICENSE](LICENSE)（英語）を参照。
