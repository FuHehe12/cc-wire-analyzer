# Changelog

## v0.2.0 - 2026-07-14

### Changed
- **Merged into a single binary.** Was: GUI exe + CLI exe (51 MB, two files). Now: one noconsole GUI exe
  with a `serve` subcommand. Double-click → GUI for a human; `cc-wire-analyzer.exe serve` → background HTTP
  service + proxy, no window, for an agent. The agent talks to the same HTTP API the GUI already uses
  (`/api/proxy/*`, `/api/captures`, `/api/dag`). This works because a Windows noconsole binary has no
  stdout — so there was never a way for a CLI subcommand to print back to an agent anyway; HTTP is the
  right channel. macOS is a single binary too (it never had the console/windowed split). See
  [docs/AI_USAGE.md](docs/AI_USAGE.md). `cli.py` stays in the source tree as a developer convenience
  (`uv run python src/cli.py`), but is no longer packaged or shipped.

### Added
- Copy support in the UI: a **Copy** button on every content block (copies the full text even when
  collapsed), a **custom right-click menu**, and a **Ctrl/Cmd+C** handler. pywebview disables WebView2's
  native context menu outside debug mode, and its WebKit backend builds no Edit menu at all — so on macOS
  Cmd+C did nothing. Copying is now handled entirely in the frontend and behaves the same on both platforms.
- **Response headers panel** in the detail view. The proxy had been recording `response.headers_safe` all
  along and the UI simply never showed it — throwing away the most valuable thing at this layer:
  `anthropic-ratelimit-*`, `request-id`, `x-should-retry`, the model the upstream actually served.
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
  macOS quit paths raise. Verified on macOS (pywebview 6.2.1): both red-dot and Cmd+Q restore `BASE_URL`
  and clear the marker — the source-level assumption (`closing` = synchronous `Event(self, True)`, both
  Cocoa quit paths route through `should_close()`) still holds unchanged in 6.2.1.
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
- **Non-streaming responses lost their usage, content blocks and stop reason.** The non-SSE branch looked
  for token counts only at the *top level* of the JSON (the shape `count_tokens` happens to return), while
  a normal `/v1/messages` response nests them under `"usage"`; and `content_blocks` / `stop_reason` were
  only ever parsed in the SSE branch. Claude Code's **security-classifier calls are non-streaming** — they
  run in the background of every session, are invisible to the user, and cost real money (551 input +
  28,224 cached, measured). Their cost was being thrown away by the one tool meant to reveal it.
- **A failed capture write was silently swallowed.** On a full disk, a permissions problem or a locked
  file, `append()` dropped the `OSError` and carried on — while the LIVE deque and SSE push, sitting
  outside the `try`, kept firing. The UI went on ticking with new captures while nothing reached the disk.
  Write failures are now counted, logged, surfaced in `/api/proxy/status` and shown as a red banner.
  (Forwarding is still never blocked by a write failure — that part was right.)
- The DAG nodes' token counts were always empty, and the CLI's token totals always 0: both read the short
  `usage.input` keys while SSE aggregation produces Anthropic's full names (`input_tokens`,
  `cache_read_input_tokens`). Key normalization now lives in exactly one place (`classifier.usage_norm`) —
  the bug appeared twice precisely because that logic had been copied around.
- The upstream error's actual cause was never displayed. The proxy records `{kind, detail}` on a
  connect/timeout failure, but the UI only rendered `kind`/`status`/`body_snippet` — so a failed upstream
  connection showed up as a bare `connect`, with the reason discarded. Ironic, for a debugging tool.
- `auto_start_proxy` was a dead setting, like `retention_days`: the settings page offered the toggle,
  stored it faithfully, and nothing ever read it. Now wired up.
- The self-test's mock SSE used token key names that do not exist in reality (`input`, `output` instead of
  `input_tokens`, `output_tokens`), which is why the key mismatch above stayed invisible. Fixed, and a
  non-streaming upstream case was added — the whole non-SSE path had never been asserted on.
- **Long-text translation failed silently.** `_llm_chat` sent no `max_tokens` (upstream's small default
  truncated long output) and timed out at 120 s; on failure the UI only flashed a toast and left the
  translation area blank, so the user saw an empty "重译" with no reason. Now sets `max_tokens`, raises the
  timeout to 180 s with a dedicated `timeout` error code, and **persists the error in the result area**
  (with `error_code` + the upstream `finish_reason` hint, e.g. length / content_filter) instead of
  vanishing. Verified: a 106 K-character security prompt (truncated to 20 K) translates in ~38 s.
- **API Key / Base URL with non-ASCII characters** produced an opaque `'latin-1' codec can't encode…`
  traceback (HTTP headers are latin-1). Zero-width spaces and full-width characters sneak in easily when
  copying from web pages. Now caught up front with a human-readable message naming the offending character.
- Translation/explain output sometimes leaked the `<text>` / `<content>` delimiter tags the engine wraps
  content in. They are now stripped from the result.

### Removed
- **The standalone CLI binary** (`cc-wire-analyzer-cli.exe`) — folded into the GUI binary's `serve` mode
  (see Changed). The "Header redaction" toggle below is also gone.
- The **"Header redaction" toggle**. It never did anything (`_redact()` was always applied unconditionally),
  and rather than wire it up we removed it: making it real would mean offering to write API keys in
  plaintext into the capture files — the same files an agent now reads. Redaction is
  unconditional and no longer pretends to be optional.
- `config.read_port()` — dead since the shell stopped being a separate process.

## v0.1.0

Initial open-source release.
