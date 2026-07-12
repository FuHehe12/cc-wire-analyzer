# CLAUDE.md

Project context for AI assistants (Claude Code / Codex / etc.) working in this repo.

## What this is

CC Wire Analyzer — a local MITM proxy desktop app that transparently records and analyzes all HTTP traffic between Claude Code and its upstream endpoint. Covers the wire level that complements jsonl-based conversation analyzers and OTLP telemetry. See [README.md](README.md) for the user-facing intro.

## Architecture

- `src/desktop.py` — pywebview shell. Starts `app.py` (Flask) on a dynamic port (5051–5100) in a background thread, opens a native window (WebView2 on Windows / WebKit on macOS). Owns crash-restore of settings on exit.
- `src/app.py` — Flask entry. Serves `/api/*` (UI backend) + a catch-all that transparently proxies everything else to the upstream.
- `src/proxy.py` — `forward(path)`: streaming SSE via `httpx`, aggregates content_blocks/usage while forwarding.
- `src/settings_guard.py` — **the safety module**. The only thing allowed to touch `~/.claude/settings.json`, and only the `ANTHROPIC_BASE_URL` field. Backup / atomic write / restore + crash protection (atexit/signal/excepthook) + orphan-marker recovery.
- `src/capture_store.py` — append-only JSONL recording + in-memory deque + LIVE SSE broadcast + clear/archive.
- `src/classifier.py` — request classification (kind) + DAG build (lanes + seq/trigger/near edges) for the timeline view.
- `src/templates/index.html` — the entire frontend (HTML + CSS + vanilla JS, no build chain, no framework). Three locales (`I18N={zh,en,ja}`) + `t18()`.
- `src/static/fonts/` — bundled fonts (Inter / JetBrains Mono / Noto Sans SC, all SIL OFL).
- `src/static/{marked.min.js,purify.min.js}` — vendored for offline use.

## Safety invariants (never break these)

1. **Only `ANTHROPIC_BASE_URL`** may be modified in `~/.claude/settings.json`. Restore = "write back original value" (or delete the key if it was originally absent), **never full-file rollback** (concurrent edits to other fields must survive).
2. **Stop/restore is bulletproof** — atexit + signal + excepthook + orphan-marker. CC must never be left pointing at a dead proxy port.
3. **All upstream-rendered content goes through DOMPurify** (marked.js output is sanitized) — upstream responses are untrusted, storage-XSS must stay impossible.
4. **`date`-typed API inputs are validated** (`YYYY-MM-DD` format + semantic) to prevent path traversal in capture clear/archive.
5. **AI-explain isolation is hardcoded** — the guard head/tail around user content can't be overridden by the user-editable prompt; literal `</content>` in content is escaped.

## Conventions

- **Cross-platform**: Windows (WebView2) + macOS (WebKit/pyobjc). Platform-specific code guarded by `sys.platform`. macOS builds verified by CI (`.github/workflows/release.yml`) + contributors, not locally (maintainer is on Windows).
- **No build chain / framework** for the frontend — keep `index.html` self-contained.
- **i18n**: any user-visible string change must update all three locales (`zh`/`en`/`ja`).
- **Fonts**: bundled (cross-platform visual consistency). Don't replace with non-redistributable fonts.

## Verify before committing

```bash
uv run python src/settings_guard.py --self-test    # settings guard
uv run python src/proxy_selftest.py                 # proxy e2e
uv run python -m py_compile src/*.py                # syntax
```

If frontend changed, exercise the UI at `http://127.0.0.1:5051/` (dev server reads templates live).

## Open-source housekeeping

- License: MIT (code) + CC BY 4.0 (documentation/prose) + SIL OFL (fonts). Third-party notices in [LICENSE](LICENSE).
- Releases built by CI on `v*` tags.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide.
