# CC Wire Analyzer — Understand Claude Code's Thinking, Prompts & Subagents

Wondering why a hidden safety classifier failed, why auto mode suddenly slowed down, what prompt a subagent received, or what a thinking block written in mixed languages means? CC Wire Analyzer records a local session and turns those hidden steps into something you can read, translate, and compare: thinking blocks, system prompts, tool calls, subagent prompts, upstream errors, and token usage.

It is for the moment when Claude Code's own session view tells you that something happened, but not why. Select captured content to translate it or ask an AI endpoint you configure to explain it; the original stays beside the explanation.

[中文](README.zh.md) · [日本語](README.ja.md)

[Website](https://fuhehe12.github.io/cc-wire-analyzer/) · [Download latest release](https://github.com/FuHehe12/cc-wire-analyzer/releases/latest) · [Documentation](docs/README.md) · [Changelog](CHANGELOG.md)

**Windows & macOS · optional translation / AI explanation · recordings stay local · no telemetry**

## Why you'd use it

Use it when Claude Code's surface-level session view leaves the important question unanswered:

- **A safety-classifier error.** Find the hidden request that failed, read the upstream message,
  and see which prompt, model setting, or tool call was involved.
- **A slow automatic mode.** Follow the timeline instead of guessing whether Claude Code is
  thinking, retrying, counting tokens, or waiting on an auxiliary call.
- **A sudden burst of subagents.** See who spawned whom, the exact Task/Agent prompt, and the
  context each subagent received.
- **Thinking in English or several languages.** Translate the selected thinking or prompt while
  keeping the original visible for comparison.
- **A question worth handing to another agent.** The recording is machine-readable, so you (or
  another agent) can search, cross-check, and diagnose it without reproducing the moment.

## Screenshots

| Captures | Timeline DAG |
|---|---|
| ![Captures](docs/screenshots/en/view-a-captures.png) | ![Timeline](docs/screenshots/en/view-d-dag.png) |

| Request detail | Settings |
|---|---|
| ![Detail](docs/screenshots/en/view-b-detail.png) | ![Settings](docs/screenshots/en/view-c-settings.png) |

| Analyse — snapshots & diff |
|---|
| ![Analyse](docs/screenshots/en/view-e-analyse.png) |

Shown in Dark Professional, the default since v0.4.7. Settings also offers Classic Warm (the
pre-v0.4.7 interface) and Lab Daylight; the choice is local to the interface and never touches
your proxy configuration.

## How to use it: from capture to diagnosis

The shortest path is: **launch → start recording → reproduce the problem → scan the capture list → open the detail and timeline views**. You do not need to understand HTTP first; start with one real request.

### 1. Record one session

1. Download a Windows or macOS build from [Releases](../../releases) and launch it.
2. Click **Start proxy** on the Captures tab, then use Claude Code normally and reproduce the behavior you want to inspect.
3. Stop the proxy or close CCWA. The session is now in that day’s capture list.

### 2. Read the capture list first

Each row is one upstream request. Start with:

- **Type**: main, title, safety review, subagent, compaction and other auxiliary calls; hidden calls are separate rows too.
- **Duration and TTFT**: tell whether the model is thinking, retrying or waiting on an auxiliary call.
- **Tokens and cache**: show which turn suddenly grew, or whether context was repeatedly read from cache.
- **Status and summary**: red failures, upstream errors, review results and response summaries are usually the first clue.

If automatic mode slows down, find the outlier by duration first. If a safety classifier is involved, start with the safety or failed rows instead of guessing from the whole session.

### 3. Open the detail to see what the model actually received

Click any row and expand the parts relevant to your question:

- Expand **System** to inspect the complete system prompt, identity block and context reminders; translate selected English text while keeping the original beside it.
- Expand **thinking**, **Messages** and **Tools** to compare reasoning fragments, user messages, tool definitions and tool calls.
- For unfamiliar fields, use **Format**, then copy one block or ask your configured AI endpoint to explain it.

This answers “why did it do that?”, “what prompt did the subagent receive?” and “why did the safety review fail?” instead of leaving you with only Claude Code’s final summary.

### 4. Use the timeline and Analyse views for cross-request problems

- **Timeline** connects main sessions, subagents and auxiliary calls in lanes; follow the derivation edge to see who spawned whom, then look for waits, retries and red error nodes.
- **Analyse** saves a request or prompt segment as a snapshot and compares turns, useful for prompt drift, context changes and invisible character differences.
- For batch searches, use the local API or [AI usage guide](docs/reference/AI_USAGE.md) and let an agent read the recordings and return a diagnosis.

Network forwarding, data locations, the full API and security boundaries are documented in [docs](docs/README.md) for readers who need them.

## Features

- **Zero intrusion** — only edits `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`; token, model mapping, OTLP config all preserved. Closing the app byte-restores the file.
- **Works with official-direct and third-party endpoints** — no `ANTHROPIC_BASE_URL` (direct to Anthropic) works too, falling back to capture the official endpoint; if present, follows it (e.g. a gateway configured via [cc-switch](https://github.com/farion1231/cc-switch)).
- **Transparent streaming** — SSE is forwarded while recorded; CC feels identical to a direct connection.
- **Crash protection** — atomic writes + per-start backup + atexit/signal/excepthook triple restore + orphan-backup recovery.
- **Timeline DAG** — swimlane view; each main session gets its own color across the lane header, axis, node border, and edges; subagent/auxiliary nodes carry a dot in their related session's color so you can see what spawned what at a glance.
- **Detail tools** — translate, "ask AI what this does" (with prompt-injection guard), format/pretty-print; UI supports **Chinese / English / Japanese** switch (instant, persisted).
- **Snapshots & diff (Analyse tab)** — back up a prompt or a whole recording as a snapshot, then diff them. Reveals differences you cannot see (CC's character watermark for Chinese users — `-`/`/` date swaps and apostrophe homoglyphs — shown as visible sentinels). Extracts the reasoning chain in three layers under an enforced budget; multi-turn analysis chat with the built-in model. A snapshot is one request, not a session.
- **Clear recordings** — clear a day's captures (direct delete / archive-to-zip then delete), with inline two-step confirm.
- **Blind-spot radar** — `GET /api/unknowns` flags every protocol value the tool doesn't yet recognize (new block types/fields, unhandled request fields, non-standard enums, the beta-feature tail), each with a content snippet and the beta features it appears alongside. It's the early warning when Claude Code ships a new beta — and, when porting the analyzer to another agent harness, the discovery tool that turns "guess the new protocol" into "scan once, confirm each unknown, build that harness's known set".
- **Cross-platform** — Windows `.exe` and macOS `.app`, built via GitHub Actions. **Fonts are bundled** (Inter + JetBrains Mono + Noto Sans SC) so the UI looks identical on every machine.

## Quick start

### Option A — download a release build

Grab the latest `cc-wire-analyzer-v<version>-windows.exe` or `cc-wire-analyzer-v<version>-macos.zip`
from [Releases](../../releases). No Python needed. The version is in the file name and in the file's
own properties (Windows: Details tab; macOS: Get Info), so you can tell builds apart without opening
them. `SHA256SUMS.txt` next to them is what the in-app updater verifies a download against.

- **Windows**: double-click the `.exe`. If it warns about WebView2 missing, install [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- **macOS**: unzip, drag `cc-wire-analyzer.app` to `/Applications`. The app is **unsigned and un-notarized** (normal for a free open-source project — code-signing costs $99/year), so **Gatekeeper blocks the first launch**. Allow it once:
  - Right-click `cc-wire-analyzer.app` → **Open** → confirm **Open** in the dialog; **or**
  - On newer macOS where that's unavailable: **System Settings → Privacy & Security → scroll to the bottom → click "Open Anyway"**.
  - After the first launch, it opens normally with no further prompts. (This is an Apple security measure, not a problem with the app.)

### Option B — run from source

```bash
git clone https://github.com/FuHehe12/cc-wire-analyzer.git && cd cc-wire-analyzer
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

## If Claude Code shows API errors

Recording works by temporarily pointing `ANTHROPIC_BASE_URL` at the local proxy, and the app
restores it on exit (multiple safety nets + an orphan-marker self-heal). If CC still reports
API errors after a recording — connection refused, 401, timeouts — it's almost always a stale
or wrong `BASE_URL` left in `~/.claude/settings.json`. Fix it by endpoint type:

- **Third-party API / gateway**: open `~/.claude/settings.json` and set `ANTHROPIC_BASE_URL`
  back to your gateway's address (or switch it back with cc-switch).
- **Official Anthropic subscription**: **delete** the `ANTHROPIC_BASE_URL` field entirely —
  the official endpoint needs no base URL — then **fully quit and restart Claude Code**. CC
  reads `BASE_URL` only at startup, so editing the file while it runs won't take effect.

## Data location

| Path | Content |
|------|---------|
| `~/.cc-wire-analyzer/captures/<YYYY-MM-DD>.jsonl` | Request/response recordings (append-only) |
| `~/.cc-wire-analyzer/archives/<date>.<HHMMSS>.jsonl.zip` | Archived recordings (when you “archive then clear”) |
| `~/.cc-wire-analyzer/snapshots/snap_*.json` (+ `.chat.jsonl`, `index.jsonl`) | Snapshots you saved on the Analyse tab — never auto-deleted (`retention_days` skips them); the tab shows total disk usage |
| `~/.cc-wire-analyzer/backups/settings.json.<ts>` | settings.json backups (keeps last 5) |
| `~/.cc-wire-analyzer/config.json` | App config (ui_lang / translate / explain …) |
| `~/.cc-wire-analyzer/run.log` | Run log |

## For AI agents: drive it over HTTP

This tool is not only for humans to look at — **an agent can drive it too**. One binary, three calls:

- `cc-wire-analyzer.exe` (double-click) → opens the GUI
- `cc-wire-analyzer.exe serve` → starts a **background HTTP service + the proxy**, no window, for an agent
- `cc-wire-analyzer.exe --help` → prints the full usage guide and exits (no window)

**The manual ships inside the binary.** You do not need this repository to use the tool from an
agent: `--help` prints the guide, and once the service is up, `GET /api/ai-guide` returns the same
text plus this machine's runtime facts (actual port, absolute data paths, whether it is recording).
So the whole handoff to your own agent is one sentence:

> This machine is running CC Wire Analyzer. Read `http://127.0.0.1:<port>/api/ai-guide` and drive it
> from there. (The port is in `~/.cc-wire-analyzer/port.txt`.)

Talk to it over HTTP on `127.0.0.1` — the same endpoints the GUI uses:

```bash
cc-wire-analyzer.exe serve &                     # start the service + proxy (patches settings.json)
port=$(cat ~/.cc-wire-analyzer/port.txt)
curl 127.0.0.1:$port/api/proxy/status            # is it recording?
# …run the session you want to record…
curl -X POST 127.0.0.1:$port/api/proxy/stop
curl "127.0.0.1:$port/api/captures?date=2026-07-13"
```

One capture can exceed 5 MB, so fetch summaries first and single records by id. Full reference,
record schema, and safety notes: **[docs/reference/AI_USAGE.md](docs/reference/AI_USAGE.md)**.

On macOS it's the same single binary — `cc-wire-analyzer.app/Contents/MacOS/cc-wire-analyzer serve`.

## Optional: translate / ask-AI

The detail page can translate text or explain "what does this content do" via any OpenAI-compatible `/chat/completions` endpoint. Configure API key / base URL / model in **Settings → LLM model**. The explain feature has a built-in injection guard (the untrusted captured content is wrapped in delimiters; literal closing tags are escaped; the isolation frame is hardcoded and unaffected by your custom prompt).

## Build from source

Build steps live in [CONTRIBUTING.md](CONTRIBUTING.md#building) — kept in one place so the Windows
and macOS instructions can't drift apart. Releases are built automatically by
[`.github/workflows/release.yml`](.github/workflows/release.yml) on every `v*` tag.

## Relationship to other observability tools

This tool covers the **wire level** (raw HTTP). It pairs well with jsonl-based conversation analyzers (CC's own view) and OTLP telemetry (metrics view) — the three are complementary.

## License

- Code: **MIT**.
- Documentation and prose (README / docs / in-app text): **CC BY 4.0** — credit the source if you reuse it.
- Bundled fonts (Inter / JetBrains Mono / Noto Sans SC): **SIL OFL 1.1**.
- Bundled JS (marked.js: MIT; DOMPurify: Apache-2.0/MPL-2.0).

See [LICENSE](LICENSE) for code, [LICENSE-DOCS](LICENSE-DOCS) for documentation and prose, and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) for bundled dependencies. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup.
