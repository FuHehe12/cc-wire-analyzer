# Contributing to CC Wire Analyzer

Thanks for your interest in improving this tool! This is a short guide for development setup and the conventions to follow.

## Development setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS (instals pyobjc for the WebKit backend)
```

Run the app in development (reloads templates on refresh, no rebuild needed):

```bash
uv run python src/desktop.py          # desktop window (the real entry point)
uv run python src/app.py              # server-only, for browser debugging at http://127.0.0.1:5051/
uv run python src/dev_seed.py         # seed 10 demo captures to exercise the UI (multi-lane + subagent + aux)
uv run python src/settings_guard.py --self-test   # verify the settings.json guard
uv run python src/proxy_selftest.py              # end-to-end proxy forwarding self-test
```

## Architecture (one paragraph)

`desktop.py` is the pywebview shell — it starts `app.py` (Flask) on a dynamic port (5051–5100) in a background thread and opens a native window. `app.py` serves both `/api/*` (UI backend) and a catch-all that transparently proxies everything else to the upstream (`proxy.py`, streaming SSE via `httpx`). `capture_store.py` does append-only JSONL recording + in-memory deque + LIVE SSE broadcast. `settings_guard.py` is the safety module: it's the only thing allowed to touch `~/.claude/settings.json`, and only the `ANTHROPIC_BASE_URL` field. `classifier.py` infers request kinds and builds the timeline DAG. The entire frontend is one file: `src/templates/index.html` (HTML + CSS + vanilla JS, no build chain, no framework).

## Cross-platform notes

- Windows uses WebView2 (system-provided). macOS uses WebKit via `pyobjc`.
- Platform-specific code in `desktop.py` must be guarded by `sys.platform` checks.
- The maintainer develops on Windows — **macOS builds are verified by CI ([`.github/workflows/release.yml`](.github/workflows/release.yml)) and by macOS contributors**, not locally. If you're on macOS, please test builds before release.

## Bundled assets

- Fonts (`src/static/fonts/`): Inter, JetBrains Mono, Noto Sans SC — all SIL OFL. Don't replace with non-redistributable fonts.
- `marked.min.js`, `purify.min.js`: vendored for offline use. DOMPurify sanitization of all upstream-rendered content is a security requirement — don't bypass it.

## Building

- Windows: `uv run pyinstaller build.spec` → `dist/cc-wire-analyzer.exe`
- macOS: `uv run pyinstaller build-mac.spec` → `dist/CCWireAnalyzer.app`
- Tagging `v*` triggers CI to build both and publish a Release.

## Before submitting a PR

1. `uv run python src/settings_guard.py --self-test` passes.
2. `uv run python src/proxy_selftest.py` passes.
3. If you touched the frontend, exercise the affected UI in a browser at `http://127.0.0.1:5051/` — the dev server reads templates live, no rebuild needed.
4. If you added/changed user-visible strings, update **all three** i18n locales (`zh` / `en` / `ja`) in `index.html`.
5. Don't commit `dist/`, `build/`, or anything under `~/.cc-wire-analyzer/` (they're gitignored).

## Safety invariants (don't break these)

- Only `ANTHROPIC_BASE_URL` may be modified in `settings.json`. Restore uses "write back the original value" (or delete the key if it was absent), never full-file rollback — so concurrent edits to other fields survive.
- Stop/restore must be bulletproof (atexit + signal + excepthook + orphan-marker recovery). CC must never be left pointing at a dead proxy port.
- `date`-typed API inputs are validated (`YYYY-MM-DD`) to prevent path traversal in capture clear/archive.

Issue reports and PRs welcome.
