# Changelog

## Unreleased

### Added
- **CLI for AI agents** (`cc-wire-analyzer-cli`) — the tool is no longer only for humans to look at.
  Headless subcommands, all emitting JSON: `proxy start/stop`, `status`, `restore`, `paths`, `dates`,
  `list`, `get`, `grep`, `dag`, `stats`, `clear`. Output is truncated by default and says so, because a
  single capture can exceed 5 MB and would otherwise blow up an agent's context. Ships as a **separate
  console binary** — the GUI build is windowed and has no stdout, so subcommands on it could never print
  anything. See [docs/AI_USAGE.md](docs/AI_USAGE.md).
- `restore` command — repairs a `settings.json` left pointing at a dead proxy port without launching the
  GUI. Previously the only self-heal ran at the *next app start*; if the app was force-killed, Claude Code
  stayed broken until the user happened to reopen the tool.
- Copy support in the UI: a **Copy** button on every content block (copies the full text even when
  collapsed), a **custom right-click menu**, and a **Ctrl/Cmd+C** handler. pywebview disables WebView2's
  native context menu outside debug mode, and its WebKit backend builds no Edit menu at all — so on macOS
  Cmd+C did nothing. Copying is now handled entirely in the frontend and behaves the same on both platforms.
- `tools/lane_probe.py` — dumps the candidate signals for telling main threads from subagents
  (`X-Claude-Code-Session-Id`, `cc_entrypoint`, presence of the `Agent` tool, system-block structure,
  spawn-prompt alignment) so the classifier can be calibrated against real traffic instead of guesses.
- `CCWA_HOME` / `CCWA_CLAUDE_SETTINGS` environment overrides, and `src/cli_selftest.py`. The most
  dangerous path in this project — rewriting the user's `~/.claude/settings.json` — previously could not
  be tested end-to-end without experimenting on the user's real Claude Code config. Now it runs against a
  temp directory.

### Fixed
- **Exit did not restore `ANTHROPIC_BASE_URL`.** Restoration was hung off `webview.start()` returning, but
  on macOS Cmd+Q / red-dot close go through `NSApplication.terminate:` → C `exit()`, which unwinds no
  Python stack and runs no `atexit` hooks. `settings.json` was left pointing at a dead local port and
  **Claude Code could no longer reach any upstream** — after the tool had already been closed. Now hooked
  to the window's `closing` event, the only event pywebview dispatches synchronously, and the one both
  macOS quit paths raise.
- **Stale recovery marker could delete the user's config.** `recover_from_orphan()` acted on the marker
  file without ever checking what `settings.json` currently contained. If the app was killed while patched
  and the user then set their own `ANTHROPIC_BASE_URL` (e.g. via cc-switch), the next launch would
  overwrite it — or, for a `had_key: false` marker, *delete the key outright*. Recovery now only proceeds
  when the current value still equals the address we patched in. (`_is_local_proxy_url()` had been sitting
  in the code unused since the marker refactor; the guard is back.)
- **Retention was a dead setting.** The settings page promised "captures older than N days are cleaned up
  automatically" and nothing in the codebase ever read `retention_days`. Recordings accumulated forever —
  13 records already weigh 5.6 MB. Now enforced at startup, with the result reported back to the UI, and
  available as `clear --older-than N`.
- Token totals in the CLI read the short `usage.input` keys, but SSE aggregation produces Anthropic's full
  names (`input_tokens`, `cache_read_input_tokens`) — every token count came out as 0.

## v0.1.0

Initial open-source release.
