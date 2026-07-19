# Changelog

## v0.3.2 - 2026-07-19

### Fixed
- **Timeline (DAG) view silently truncated at 1000 records, and the whole UI got sluggish
  on busy capture days.** A heavy day of recording easily exceeds 1000 requests (measured:
  2993 records / 826 MB in a single day, ~276 KB average per record), and the pipeline had
  four compounding bottlenecks:

  1. `list_full()` hard-capped the DAG input at 1000 records — on the measured day the
     timeline showed 1000 nodes / 5 lanes instead of the real 2993 nodes / 13 lanes;
     the back two-thirds of the day never made it into the graph.
  2. `list_captures()` `readlines()`-ed the entire main file and JSON-parsed the newest
     200 lines (which are the largest ones — context grows over the day) on every list
     request: measured 3.3 GB peak memory and 2.6 s of disk reading for one 826 MB day.
  3. `/api/dag` re-read and re-parsed the whole capture file on every call, and the
     frontend re-calls it (800 ms debounce) on every live capture event — more traffic
     meant more calls, each slower than the last.
  4. `get_capture()` linear-scanned and JSON-parsed line by line — worst case parsing the
     entire 826 MB file to open one detail view.

  Root fix: **write-time lightweight index**. `append()` already has the full record in
  memory, so it now also writes a 1–2 KB index record (`{date}.idx.jsonl`) carrying every
  field the list/DAG need plus the byte offset of the full record in the main file.
  Lists and the timeline read only the index (2993 records ≈ 5 MB, ~50 ms), the 1000-record
  cap is gone, and detail views seek directly to the record (measured 22 ms for the last
  record of an 826 MB day). Index records hold their own offsets, so a missing/stale index
  (old captures, crashed writes) self-heals by incremental backfill from the main file.
  Index write failures never block forwarding (same invariant as the main write) — they are
  counted, logged, surfaced via `/api/proxy/status` (`write_errors.idx_count`), and healed
  by backfill. Frontend: live updates to an existing list row now replace that single row's
  DOM instead of rebuilding the whole list per SSE event.

  Measured on the 826 MB / 2993-record day: DAG 1000→2993 nodes (complete), build 147 ms
  after a one-time 5 s backfill; capture list 2.6 s / 3.3 GB → 1 ms / 0.1 MB; detail open
  seconds → 22 ms.

- **Timeline view froze during live recording on busy days (frontend), and 3000-node graphs
  were unreadable.** Even with the fast index backend, every live capture event triggered a
  full frontend rebuild of the graph — measured 1.7 MB of innerHTML (2993 node divs + 3725
  SVG paths), ~1.1 s of main-thread work every ~1 s while traffic flowed. The layout is
  time-ordered and new nodes only ever append at the bottom, so live updates now **append
  only the new nodes/edges** (measured 2 ms, layout verified identical to a full rebuild
  node-by-node); a full re-render happens only on view/date/filter switches, lane-count
  changes, or turn-tier reclassification. Two new toolbar filters keep big days readable:
  **Hide tool-loop steps** (collapses tool-loop middle steps) and **Hide auxiliary calls**
  (collapses title/security/count calls — measured 1/4 of all nodes on the reference day),
  taking the 2993-node day down to 2050 visible nodes / 12 lanes. Node CSS `transition: all`
  narrowed to specific properties. All labels in zh/en/ja.

### Added
- **Collapse runs of consecutive errors into one red "×N" card.** A dead-upstream day floods
  the graph with retry errors (measured 2029 error nodes in one day — "errors never get
  visually downgraded" is a deliberate design rule, but 2029 full-height cards made the graph
  168k px tall and unreadable). Consecutive errors in the same lane (≥2) now fold into a
  single striking red card with count, time span, and first summary — visible nodes on the
  reference day drop 2993 → 969. Click to expand into individual error cards (first card
  gets a collapse badge); live-appended errors extend the count in place with zero re-layout.
  Sequence/trigger edges resolve folded members to the run card's position.
- **Lane picker in the timeline toolbar.** Fit-width zoom on a 13-lane day is ~29% — text
  unreadable. The new "Lanes" dropdown lists every lane (color dot, name, count) and toggles
  visibility; hidden lanes free their column so remaining lanes fit at a larger zoom (one
  main lane + agent + aux → 100%). Selection resets on date change (lane ids differ per day).

## v0.3.1 - 2026-07-18

### Fixed
- **Self-reference loop that made the proxy forward requests to itself (P0 regression introduced in v0.3.0).**
  When `~/.claude/settings.json`'s `ANTHROPIC_BASE_URL` pointed at the proxy's own local address
  (leftover patch state / cc-switch switched to a "recording endpoint" profile / hand edit),
  `snapshot_original()` accepted that self-referential URL as the "real upstream". `forward()` then
  routed CC's requests to "the upstream" = itself → infinite recursion → every request
  504 GATEWAY TIMEOUT. The marker persisted `original == listen`, so stop/restart couldn't recover
  (restore wrote back the polluted original; cross-restart orphan recovery prolonged the deadlock).
  v0.2.0 was unaffected — the code path wasn't reachable without the watcher. Three-layer fix:

  1. **`snapshot_original()` self-reference guard.** A BASE_URL that resolves to the proxy's own
     listener (loopback host + same port) now raises `SettingsGuardError` with a plain-language
     hint instead of starting. Port-precise comparison, so legitimate local OpenAI-compatible
     upstreams (e.g. a local vLLM at `:8080`) are still accepted.
  2. **`check_orphan_backup()` marker.original guard.** If the marker's recorded `original` is a
     loopback address (meaning it was polluted by the v0.3.0 bug), clear the marker only — never
     write the self-reference back to settings.json (otherwise cross-restart recovery perpetuates
     the loop).
  3. **`proxy.forward()` deep defense.** If the upstream equals our own patched listen address,
     refuse to forward and return 502 with a plain-language error (the snapshot guard is the first
     line; this is the last).

  Root cause is "guard function existed but caller was missing": `_is_local_proxy_url()` was
  already used by `check_orphan_backup` and `restore`, but not by `snapshot_original` or
  `recover_from_orphan` — the two entry points that write an externally-read URL into
  `_original_base_url`. Hardened into a safety invariant: *any* entry point that reads a URL from
  outside (file/marker) intending to record it as `original` or write it back to settings.json
  must pass a self-reference check.

## v0.3.0 - 2026-07-17

### Added
- **Three-tier visual hierarchy in the timeline (DAG) view.** Every request used to be an
  equally sized card, so one user message followed by a long tool loop filled the main lane
  with same-weight nodes and drowned the story. Nodes are now tiered by two purely structural
  criteria (no semantic guessing, validated against three days of real captures first):
  a request whose last user message carries real text (not just `tool_result` blocks) starts
  a **user turn** → full card; tool-loop follow-ups → **slim rows** (compressed row height,
  reduced opacity — long loops visually contract); a turn with zero tool calls (asking the
  agent to recap, follow-up questions, clarifications) → **💬 chat-only turn** with a dashed
  border. Error nodes are never demoted. Legend explains the tiers in all three languages.
- **External-change watchdog for `settings.json`.** Switching endpoints with cc-switch (or editing
  the file by hand) rewrites `ANTHROPIC_BASE_URL`, so CC silently bypasses the proxy while the UI
  still says "running" — monitoring stops with no sign of it. A background thread now compares the
  value every 2 s (a few-KB JSON read; deliberately no mtime baseline, which had a race window right
  after patching, and no file-watcher dependency). On mismatch it flags the state as disconnected,
  clears the marker, **never touches the file** (the new value is the user's intent), surfaces a
  red banner with the new upstream, and offers one-click **Re-attach** — a plain start that
  snapshots and captures the new upstream. `/api/proxy/status` exposes `external_change` so an
  agent driving `serve` mode sees it too.
- **Exit logging that can answer "how did the last session end?".** `run.log` used to record
  shutdowns only as a side effect (a `restored BASE_URL` line, and only if the proxy was running) —
  a session on 07-15 left literally one line and no trace of how it ended. Now: a startup banner
  (`=== started mode=gui|serve pid=… version=… port=… ===`), explicit exit lines on every path
  that can write one (window close, GUI shutdown, user stop via API, atexit, signals), and a
  plain-language "previous process did not exit cleanly (killed / power loss / crash)" warning
  when orphan recovery triggers. A banner with no matching exit line now reliably means a hard kill.

### Fixed
- `run.log` was written in the OS locale encoding (GBK on Chinese Windows), so Chinese log lines
  showed as mojibake in any UTF-8 tool. Logging is now explicitly UTF-8 (historical GBK segments
  are left as-is).
- The release publish job crashed on checkout at its first tag-triggered run: `fetch-tags: true`
  conflicts with the ref the checkout action itself fetches for the triggering tag
  ("Cannot fetch both … to refs/tags/…"). The annotated tag object (used as the release-notes
  fallback) is now fetched explicitly after checkout instead.

### Changed
- **Release notes are now sourced from `CHANGELOG.md`.** The release workflow had used
  `generate_release_notes`, which groups entries by pull request — meaningless for this
  solo-commit project, so the v0.1.0 and v0.2.0 release pages showed only a bare
  "Full Changelog" link while the detailed changelog went unread. The release job now
  extracts the current tag's section from this file (with tag-message and placeholder
  fallbacks), so release pages carry the full changelog automatically.

### Added
- Chinese translation of this changelog at [`CHANGELOG.zh.md`](CHANGELOG.zh.md), kept in
  sync with the English version. Release notes on GitHub stay English; the Chinese file is
  a documentation mirror.

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
