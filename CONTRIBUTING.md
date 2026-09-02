# Contributing to CC Wire Analyzer

Thanks for your interest in improving this tool! This page covers **environment setup, building,
and the PR checklist**.

> **Before you write any code, read [`docs/reference/开发约定.md`](docs/reference/开发约定.md) (Development Guide).**
> It is the single source of truth for this project's conventions — safety invariants, the
> recurring bug types, the defensive-design table, the subagent-identification ruling, the
> self-tests, and the frontend rules. Counts grow over time, so the guide holds them — not this
> page. The guide is in
> Chinese — if that's a barrier, open an issue and we'll help.
>
> Those conventions used to be summarised on this page too. That copy silently drifted: it listed
> 2 self-tests when there were 6, and 3 invariants when there were 8. So this page no longer
> restates them — it links instead.

## Development setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo> && cd cc-wire-analyzer
uv sync                 # Windows
uv sync --extra mac     # macOS (installs pyobjc for the WebKit backend)
```

Run it:

```bash
uv run python src/desktop.py          # desktop window (the real entry point)
uv run python src/app.py              # server-only, for browser debugging (port from startup log or ~/.cc-wire-analyzer/port.txt)
uv run python src/dev_seed.py         # seed demo captures to exercise the UI
```

> **Template edits need a dev-server restart** — `app.run(debug=False)` caches Jinja templates, so
> editing `index.html` and refreshing still shows the old page. Why this happens and how to verify
> a change took effect: see [`docs/reference/开发约定.md`](docs/reference/开发约定.md) §8.

## Building

- Windows: `uv run pyinstaller build.spec` → `dist/cc-wire-analyzer.exe`
- macOS: `uv sync --extra mac && uv run pyinstaller build-mac.spec` → `dist/cc-wire-analyzer.app` (the `--extra mac` installs pyobjc for the WebKit backend)
- Tagging `v*` triggers CI to build both and publish a Release.

The maintainer develops on Windows — **macOS builds are verified by CI
([`.github/workflows/release.yml`](.github/workflows/release.yml)) and by macOS contributors**,
not locally. If you're on macOS, please test builds before release. Platform-specific code in
`desktop.py` must be guarded by `sys.platform` checks.

## Bundled assets

- Fonts (`src/static/fonts/`): Inter, JetBrains Mono, Noto Sans SC (all SIL OFL; full list in the
  README license section). Don't replace with non-redistributable fonts.
- `marked.min.js`, `purify.min.js`: vendored for offline use. DOMPurify sanitisation of all
  upstream-rendered content is a security requirement — don't bypass it.

## Before submitting a PR

1. **Run all seven self-tests.** The commands are listed in
   [`docs/reference/开发约定.md`](docs/reference/开发约定.md) §8 — copy them from there rather than from memory,
   since the set has grown over time.
2. If you touched the frontend, exercise the affected UI in a browser (open the port from the
   startup log or `~/.cc-wire-analyzer/port.txt`) — **restart the dev server first** (see the
   template-caching note above).
3. If you added or changed user-visible strings, update **all three** i18n locales
   (`zh` / `en` / `ja`) in `index.html`. The three key sets must match exactly.
4. Check your change against the safety invariants in [`docs/reference/开发约定.md`](docs/reference/开发约定.md) §1.
   Anything that writes `settings.json`, renders upstream content, or produces output for an AI
   agent needs a second look.
5. Don't commit `dist/`, `build/`, or anything under `~/.cc-wire-analyzer/` (they're gitignored).

## Where things are documented

| I want to… | Read |
|---|---|
| change code without breaking things | [`docs/reference/开发约定.md`](docs/reference/开发约定.md) |
| understand how the app is put together | [`docs/reference/架构总览.md`](docs/reference/架构总览.md) |
| call the HTTP API | [`docs/reference/API契约.md`](docs/reference/API契约.md) |
| drive the tool from an AI agent | [`docs/reference/AI_USAGE.md`](docs/reference/AI_USAGE.md) |
| understand the UI | [`docs/reference/界面导览.md`](docs/reference/界面导览.md) |
| understand what Claude Code actually sends | [`docs/methodology/报文解读.md`](docs/methodology/报文解读.md) |
| edit the docs themselves | [`docs/文档维护策略.md`](docs/文档维护策略.md) |

Issue reports and PRs welcome.
