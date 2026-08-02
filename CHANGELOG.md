# Changelog

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Detailed change history in the sections below. Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed to use it from an agent.
- **Current status**: **v0.4.6 released** (2026-08-01). A correctness pass driven by using the
  tool the way an agent does: `grep` searched only 14% of a request and could not say so (it now
  covers every region, and every result declares its coverage); `stats` left `cache_creation`
  out of its totals (~38% of the cost); `get` without `--date` could silently return a
  stripped-down index row in place of the real record; a response whose body failed to
  decompress counted as a success in failure statistics (now its own `decode_failed` kind);
  and every inspection surface — API and CLI alike — can be filtered by session, so a second
  Claude Code can audit a first one through the proxy without seeing its own traffic. On the
  human side: a loading badge now shows while a slow date loads, and the protocol-extension
  baseline no longer false-alarms on recordings from before a beta flag was renamed.
  The preceding **v0.4.5** was a correctness and readability
  pass for the timeline when a capture holds more than one session and spawned subagents — the
  chart now matches what actually happened. Auxiliary calls (title / security / count_tokens)
  attach to their owning session lane by session id, not to whichever main lane was latest in
  time; subagent lanes are keyed by CC's own `X-Claude-Code-Agent-Id` header, so a lane joins
  straight to the subagent's own jsonl transcript; hiding a main lane cascades through the spawn
  chains and aux calls it owns; and subagent lanes are tinted with a washed version of their
  spawner's color, so a spawn family reads as one color family. Plus fixes from real use: a
  `loadDag` race could leave the timeline on the wrong day after fast date switches; "I raised
  max_tokens, why is it still cut off" now has an answer (three causes, named); copy and selection
  work across the packaged app; and `serve` no longer exits on a machine that has no settings.json yet.
  The preceding **v0.4.4** was a usability release — surviving midnight, readable small text, and
  a 90–200% interface-scale setting.
  **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed
  `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced,
  delete it yourself.
- **Next steps**:
  1. **Failure grouping across days — landed in Unreleased.** `/api/diagnose/trends` now answers
  "new or recurring?" with per-day curves, recurring/rising/declining/sporadic tags, and
  host/model/cc_version slices (HTTP-only, no GUI). Still open: hardening recurring patterns
  into doctor rules automatically — `effort_max_rejected_upstream` came from a manually-spotted
  recurring failure, and closing that loop end-to-end is the remaining half.
  2. **Recording-blind-spot audit: closed (both halves).** The 260731 *protocol-side* audit
  (against what CC declares: headers, body fields, SSE branches) found nine gaps, all addressed.
  The *capability-side* half — running each CC ability through the proxy and checking the recording
  — is now done too: 14 captures across 7 dimensions, core parsing zero hard bugs, one
  documentation posture fixed (see v0.4.3). Method in `docs/开发指南.md` §2.5; portable version in
  unit 0 of `docs/问题域手册.md`.
  3. **Identity residual** (deferred): interactive-mode (`cc_entrypoint=cli`) subagents still lack a hand-verified capture. Historical captures now supply statistical evidence — 225 subagent requests, all `cc_entrypoint=cli`, all carrying the flag, no counterexample — but that is not the same as a session captured and checked against ground truth, which is what closing this actually needs.

## Unreleased

### Added
- **`/api/grep` + `/api/stats` HTTP endpoints.** Previously CLI-only — an AI had to read the
  jsonl directly to search content or count tokens, violating ai-guide rule ① ("don't read whole
  recordings"). Core logic moved to `capture_store.grep/stats` (single source, shared by CLI and
  HTTP): `/api/grep` (with coverage — which regions were searched, how much skipped) +
  `/api/stats` (kind/model/status distribution, four token fields incl. cache_creation, cache hit
  ratio, latency p50/p95). Extracting the common source prevents CLI/HTTP drift — the root cause
  of the earlier stats `cache_creation` missing-field bug. ai-guide endpoint table +
  `docs/AI_USAGE.md` updated.
- **Blind-spot radar `/api/unknowns`: one call for every value outside the known sets.** Before,
  "unknowns" could only be found by a human scanning jsonl — non-standard response block types,
  unhandled request fields, non-standard enum values, silently present but unnoticed.
  `index_record` now computes an `unknowns` block per record (values outside the `KNOWN_*` sets:
  block types/fields, request fields, stop_reason, thinking.type); `/api/unknowns?date=` aggregates
  each dimension as `{value, count, samples[≤5 ids]}` + the full beta tail in ascending frequency
  (low-frequency = protocol-drift signal) + a `known` baseline + note. One call hands an agent
  every blind spot + sample ids to investigate, driving improvements (new parsing / rendering /
  classification rules; stable ones get folded into `KNOWN_*`). Bumps `IDX_SCHEMA` 9→10. First
  sweep across 12 days / 5414 records surfaced `tool_use.caller` (464, a caller-attribution field
  never previously parsed), `thinking.type=adaptive` (3206, non-standard enum),
  `web_search_tool_result` / `tool_result` block types, `text.citations`, and `tool_choice`.
- **`quota_probe` + `hook_eval` kinds.** The 10 records that used to fall into `other` are two
  stable shapes: CC's quota probe (`user="quota"` + maxtok=1; all 9 return 429/401/timeout) and a
  StopConditions hook evaluation (system contains "stop-condition hook"; 1 record). `classify_idx`
  now fixes both before the `other` fallback; all 10 historical `other` reclassify, and
  **other drops to zero**.
- **Cross-day failure trends `/api/diagnose/trends`.** The single-day `/api/diagnose/errors` could
  not say whether today's failures are new or a recurring pattern — or which vendor / CC version
  they cluster on. `GET /api/diagnose/trends?span=N&model=&kind=` merges failures across the last
  N days (same key as errors) into three layers: a per-day curve, cross-day groups each tagged
  `recurring`/`rising`/`declining`/`sporadic` (active-day first-half vs second-half ratio), and
  global `by_host`/`by_model`/`by_cc_version` slices. HTTP-only — no GUI: the cross-day dimension
  explosion (CC version × vendor × time × error) is an AI-audit sweet spot and a human-readable
  nightmare. `diagnose.trends`/`_trend` added; reuses the single-day fingerprint/merge.
- **`index_record` indexes `host` + `cc_version` (IDX_SCHEMA 12→13).** `host` is the upstream
  netloc (the **routing vendor** — a wire-level fact, not a model→vendor guess: the same
  `claude-opus-5` can go via official / Zhipu / a relay aggregator, so the model name can't pin
  the vendor, the host can). `cc_version` is parsed from `user-agent` (`claude-cli/<ver>`; not
  redacted). Both backfill onto historical captures (`rec.upstream` / `headers_safe.user-agent`
  always existed) once the index rebuilds. Both are PUBLIC (visible in list/SSE summaries — audit
  scalars, `classify_idx` doesn't read them; same call as `session_id` in 260802).

### Changed
- **`/api/captures` list summaries now carry `session_id`.** `_IDX_PRIVATE` used to strip
  `session_id` as a "DAG classification input", so list/SSE summaries hid session ownership while
  the DAG lane exposed it — inconsistent. Under v0.4.6's session-filter scenario (two CCs side by
  side, one auditing the other), once the auditor used `exclude_session`, the remaining requests
  could neither confirm ownership in the result nor line up with `~/.claude/projects/` jsonl
  filenames — only blind inference from totals: "can filter, can't see". Hit during a real dual-CC
  recording. `session_id` is removed from `_IDX_PRIVATE`; list/SSE summaries now match the DAG
  lane. No IDX_SCHEMA bump needed (the field was already indexed at write time, 100% coverage);
  the real discriminator bits `is_subagent` / `entrypoint` / `agent_fp` stay internal.
- **List rows show a session short-code when multiple sessions are present.** The list used to
  interleave two CCs' requests by time with no ownership cue — you had to switch to the DAG to
  tell them apart. `fetchCaptures` now detects when items span multiple session_ids and shows each
  row's first 8 session chars under the time (matching the DAG lane short-code); silent for
  single-session to avoid noise. No new grid column (the 10-column px layout is fixed; adding one
  would force re-computing the tri-lingual column widths) — the short-code goes in the second line
  of the `cap-time` cell.
- **`server_tool_use` response blocks get dedicated rendering.** Previously fell through to the
  default branch (raw JSON dump), hiding what was called. `renderRespBlock` / `renderMsg` add a
  dedicated case reusing the tool_use style (`→ name {input}`), with a different chip color to
  distinguish server-side tools (web_search, webReader, etc. — tools the upstream executes on CC's
  behalf).
- **`output_config.format` is now indexed.** For the structured-outputs feature (CC forcing
  json_schema output, e.g. a title request wanting only `{title}`), `index_record` previously took
  `effort` but not `format`. It now adds a `format` field (`output_config.format.type`, e.g.
  `json_schema`); bumps `IDX_SCHEMA` 8→9 (old indexes auto-rebuild on read).
- **Detect at startup when `BASE_URL` is already a local address, and warn.** Only "BASE_URL
  points at the proxy itself" (same-port loopback, which would infinite-loop on forward) used to
  be hard-rejected; a BASE_URL that's *some other* local address — leftover from a prior run, a
  cc-switch profile contaminated with the local-proxy address, or a hand edit — was neither
  blocked nor reported, so users only noticed after "recorded everything as 504 / captured
  nothing". `snapshot_original` now records `_base_url_warning` for non-self loopback URLs (not
  rejected: could be a legitimate local gateway like `:8080` vLLM); `/api/proxy/status` exposes
  `base_url_warning`; the UI reuses the external-bar style for a prominent "check BASE_URL" prompt
  (tri-lingual). The warning persists across the whole recording and clears on the next
  `snapshot_original` recompute.
- **Blind-spot radar review: known sets expanded + the web_search chain rendered.** Deep analysis
  of the first sweep's six categories showed they are two clusters of protocol evolution, not bugs:
  the **web_search** family (`tool_choice(web_search)` → `server_tool_use` →
  `web_search_tool_result` → `text.citations`) and **advanced-tool-use / new-model thinking**
  (`tool_use.caller:{type:"direct"}`, `thinking.type=adaptive` on opus-5/k3). The known
  Anthropic-standard fields are folded into `KNOWN_*` so the radar reports only true unknowns:
  `KNOWN_BLOCK_TYPES` += web_search_tool_result + redacted_thinking; `KNOWN_BLOCK_KEYS` adds
  caller / citations / the new blocks' fields; `KNOWN_BODY_FIELDS` += tool_choice;
  `KNOWN_THINKING_TYPES` += adaptive. `index_record` now indexes `tool_choice` (which requests
  force a tool, e.g. web_search). The web_search chain is now readable — `web_search_tool_result`
  shows a result summary + count (was a raw JSON dump), and `text.citations` shows cited_text + url
  (was hidden). After the sweep, with_unknowns on a test day dropped 259→1 (the remainder is
  `_input_raw`, a genuine fallback field). Bumps `IDX_SCHEMA` 10→11.
- **Blind-spot radar v2: each unknown now carries a content snippet and its beta provenance.** v1
  reported only `{value, count, samples}` — judging an unknown meant a second `/api/captures/{id}`
  call to see the surrounding content. The payload now adds two fields per value: `snippet` (the
  value's first ~80 chars — an agent can tell at a glance what kind of thing it is) and `betas`
  (the beta features on the requests where this value appears, i.e. its *provenance* — a value
  tracking the `advanced-tool-use-*` beta tells you which capability introduced it). Underneath,
  `classifier._unknowns` was rewritten from a set of bare values to a value→snippet dict so the
  content is captured at index time. Bumps `IDX_SCHEMA` 11→12.

### Docs
- AI_USAGE.md gains "coexisting with cc-switch and other config tools" + "when the proxy needs a
  restart": saving a profile via cc-switch during recording stores the local-proxy address into
  that profile (undefendable on the tool side — settings isn't modified, only read out, so
  settings_guard can't detect it; the switch-upstream path is already covered by
  `check_external_change`'s detect-and-stand-down); opus subscription / key changes require
  `stop` + `start` to restart the proxy.
- The domain handbook (docs/问题域手册.md) unit 0 gains a structural lesson: **when reconciling
  across observation surfaces, the units don't line up directly.** Using the harness's jsonl as
  ground truth to validate a wire recording, jsonl "splits one API response into multiple lines"
  (thinking / text / each tool_use on its own line), making "line count vs request count" a
  confident-but-wrong comparison; reconcile by logical response boundary, not line count. Serves
  the 0.6.x wire↔jsonl convergence.
- README tri-lingual "is it safe" point 4 gains two notes: saving a profile via cc-switch during
  recording stores the local-proxy address into that profile (settings only read, not modified —
  undefendable on the tool side; the switch-upstream path is already covered by
  `check_external_change`); and if `BASE_URL` is already a local address when recording starts,
  the app warns you to check it (the `base_url_warning` detection above).
- **The blind-spot radar documented as a portability + protocol-drift tool.** The domain handbook
  gains unit 10 ("Blind-spot radar — protocol-drift early warning + protocol discovery on
  migration"): the radar isn't a list of what's known, it's the tool for *finding what's unknown*
  — most valuable when porting the analyzer to a new harness, where it turns "guess the new
  protocol" into "scan once, confirm each unknown, build that harness's known set". The
  maintainer's guide §2.5 expands the radar's implementation + the KNOWN_* maintenance loop
  (radar finds → human confirms it's Anthropic-standard → fold into `KNOWN_*` + bump `IDX_SCHEMA`
  → radar clears that item → only true unknowns remain). The three READMEs gain a one-line radar
  feature.

## v0.4.6 - 2026-08-01

### Added
- **Session filters on every inspection surface.** `/api/captures`, `/api/dag` and
  `/api/diagnose/errors` accept `session` / `exclude_session`, and CLI `list` / `dag` / `errors`
  accept `--session` / `--exclude-session`. The driving scenario is two Claude Code instances
  side by side — one doing work, one auditing it through the proxy: the auditor's own requests
  land in the same capture and pollute every view. Matching is by prefix, so the first few
  characters of a session id are enough; filtering happens before pagination, so `total` stays
  honest. Point `exclude_session` at the auditor's own session id and every surface shows only
  the audited traffic.
- **A loading badge while a date loads.** Switching to a date whose index needs (re)building —
  first view after an upgrade, or a big day — can take seconds to tens of seconds with zero
  feedback, and the app looked dead. A small pill bottom-right (spinner + "Loading {date}…")
  now shows whenever a capture-list or DAG request is in flight. A reference counter handles
  the overlapping pair that the DAG date chips fire, so the badge hides only when the last
  response lands, and a `finally` guarantees it never sticks. No progress bar: an index
  rebuild has no progress signal, and fake progress is worse than none.

### Changed
- **`grep` searched 14% of a request and could not say so.** `--in all` covered three places —
  the `system` field, `role=user` text, and the response's text blocks — while the rest of the
  request body went unsearched: tool definitions (44% of the body, re-sent in full every
  request), tool results (25%), tool-call arguments (8%), and `role=system`
  mid-conversation messages (6.5%), which is where Claude Code puts the skill list and its
  injected reminders. A search for a skill name returned `hits: 0` — indistinguishable from
  "searched everywhere and it isn't there". For a tool an agent drives, that is the dangerous
  shape of wrong: a confident negative it will reason from. `--in` now also accepts `sysmsg`,
  `tool_result`, `tool_use`, and `tools`; `all` means everything except `tools` (a static schema
  repeated on every request would drown every hit). And every result carries a `coverage` block
  naming what was searched, what was skipped, and the skipped share of the body — measured
  during the scan, not hardcoded — with an explicit note on zero hits. The share is reported
  only when the scan ran to completion; if matches hit `--limit` first, it is `null` rather than
  a number computed from a partial pass.

### Fixed
- **`stats` left `cache_creation` out of its token totals** — 4% of the tokens, but around 38%
  of the cost, because writing to the cache is priced 12.5–20× a read (depending on TTL).
  The normalizer had all four fields; the consumer took three. Anyone reading `stats` to
  understand spend was under-counting by a third, and under-counting precisely the part that
  says "the context is being rebuilt" — the most actionable signal there. Token totals now
  carry all four, plus a `cache_hit_ratio`. No dollar conversion is built in: rates vary by
  model, route, and TTL, so a hardcoded one would rot.
- **`get <id>` without `--date` could silently return a stripped-down record.** The date scan
  behind the CLI (`list_capture_dates`) globbed `*.jsonl`, which also matches the write-time
  index files named `<date>.idx.jsonl` — so `f.stem` yielded pseudo-dates like `2026-08-01.idx`.
  Harmless as noise in `dates`, but `get` falls back to walking history when no `--date` is
  given, index lines carry **the same `id` as the real record**, and reverse sort puts
  `"2026-07-31.idx"` *ahead of* `"2026-07-31"` — so the index line always won. The result was
  the worst kind of failure: not an error but `ok: true` with `data: null` for every body-bearing
  part (`system`, `messages`, `tools`, `request`, `response`), plus a `kind` misread as `other`
  because the classifier had no body to work with. An agent reading that would conclude "this
  request carried no system prompt". The scan now accepts only `YYYY-MM-DD` stems, which also
  covers `.archiving.*` temp files and any future derived name. Note this bug was already known
  and fixed on the GUI path — `capture_store._available_dates()` has filtered by date regex since
  the index was introduced (260719), with a comment saying it shows up "the moment index files
  exist"; the config-side twin was simply missed.
- **A response that could not be decoded was invisible to failure statistics.** When the upstream
  body fails to decompress — a gzip stream truncated mid-transfer is the observed case — the
  record keeps `status: 200` and no `error`: the detail page honestly showed `decode_error`,
  but failure aggregation reads only the index, and the index never carried the field. The
  request counted as a success while its body was gone (one sat recorded for days before being
  spotted by hand). `decode_error` is now indexed (schema v8 — old indexes rebuild automatically)
  and counts as a failure of its own kind, `decode_failed` — deliberately not merged into the
  upstream error kinds, because "the upstream refused us" and "we could not read the upstream's
  answer" are different conclusions. A real upstream error kind still wins when both are present.
- **The protocol-extension baseline no longer false-alarms on pre-rename recordings.**
  `server-side-fallback-2026-06-01` is the old name of `fallback-credit-2026-06-01` (old name
  last seen 2026-07-14, new name first seen 2026-07-25 — same date stamp, renamed between CC
  versions). The baseline held only the new name, so opening a recording from before the rename
  flagged the old one as an unknown extension. Both names are in now.

## v0.4.5 - 2026-08-01

### Changed
- **Auxiliary calls now attach to their owning session lane exactly, not to whichever main lane
  was latest in time.** Aux requests carry `X-Claude-Code-Session-Id` too — 1 163 records across
  10 days, 100 % have it, 99.7 % map to a main lane captured the same day — so the `near` edge now
  resolves through the session id and only falls back to time proximity when the owning session
  was never recorded (3 records in the whole set). On the busiest multi-session day the old
  heuristic had mis-attached 9 of 745 aux calls, and every mis-attachment also mis-colored the
  node and hid it with the wrong lane on cascade. Legend updated in all three languages
  ("aux owner"). Same audit rule as the agent-id change below: where a heuristic guess and an
  official field coexist, the official field wins. (Methodology written into `docs/开发指南.md`
  and `docs/问题域手册.md` for reuse on other harnesses.)
- **Subagent lanes are now keyed by CC's own agent id** (`X-Claude-Code-Agent-Id` header) whenever
  it is present, instead of the `md5(spawner|prompt)` key derived from prompt alignment. Evidence
  over 10 days of real captures (225 subagent requests): the header appears on every subagent
  request since CC added it (23/23 on 2026-07-31), is stable within a spawn instance, is never
  reused across instances, and — cross-checked against `~/.claude/projects/` — is the *same id*
  CC writes into `subagents/agent-<id>.jsonl` transcript filenames and async `toolUseResult.agentId`
  (3/3 match). The lane id can now be joined straight to the subagent's own jsonl transcript.
  Recordings from before the header existed keep the md5 lane key (prompt alignment stays as the
  fallback), and trigger edges — the only source of parent linkage — are still inferred by prompt
  alignment either way. The main-vs-subagent *kind* decision is unchanged (billing header).
- **Hiding a timeline lane now cascades through everything it spawned.** Hiding 主线 N also hides
  the subagent lanes it spawned — including nested chains where a subagent spawned another
  subagent — and the auxiliary calls attached to it; those rows in the lane dropdown are marked
  "hidden with 主线 N". To look at one subagent on its own, re-check it: it comes back alone
  while the parent stays hidden. Re-showing the parent restores every descendant you did not hide
  individually. (Previously only the auxiliary calls followed their main lane; subagent lanes
  stayed and kept occupying columns.) Toggling is single-click in both directions — no
  "click twice to really reopen" intermediate state.
- **Subagent lanes are tinted with a washed-out version of their spawner's color** instead of all
  sharing one flat blue. Nested spawns wash out one step further, so a whole spawn family reads as
  one color family at a glance (lane head dot, node left border, sequence edges, trigger edges all
  follow). Subagents whose spawner was never captured — Workflow spawns carry no trigger edge —
  keep the plain blue, and blue now has a meaning: "the spawner is not on this chart". The legend
  says so.

### Fixed
- **`serve` exited instantly on a machine that has no `settings.json` yet.** Fresh machines (CC
  never ran, or the file was deleted) hit `backup_file()`'s `read_bytes()` on a nonexistent file,
  the exception path in `_serve` called `sys.exit(1)`, and the log showed a clean startup line
  followed by an immediate atexit with no error. `_read_settings` now treats a missing file as
  `{}` (patching then creates a minimal file) and `backup_file` skips a file that does not exist —
  restore of "the key was never there" is a no-op anyway.
- **The one line you hand to your AI stayed Chinese no matter the interface language.** The
  translations had been there all along; the rendering was the problem. That sentence embeds this
  machine's guide URL (the port is picked dynamically), so it cannot live in a static `data-i18n`
  node — it is written by JS inside `loadConfig()`. `setLang` re-renders every other JS-built panel
  and misses the settings page, so the sentence froze in whatever language was active when the page
  was opened. Worse than a display bug: the copy button copies `S.aiPrompt`, so the interface could
  be English while the clipboard held Chinese. There is now one `renderSettingsI18n()` that owns
  every derived string on the settings page (that sentence and the backup count), called from
  `setLang`. Deliberately **not** `loadConfig()` — that would overwrite form fields the user is
  editing but has not saved yet.
- **"I raised max output tokens, saved it, and the output is still cut off."** Persistence was never
  the problem (`set_config` writes, `_llm_request` re-reads the config on every call). The setting
  did reach the upstream; what was missing is any way to tell **why** the text stopped. Three
  different causes looked identical on screen — the source text was cut by *this tool* before
  sending (20 000 characters, a cost guard that no `max_tokens` can undo), the upstream stopped at
  `max_tokens` (and the model has its own ceiling, so a larger local value may change nothing), or
  upstream content filtering intervened. All three now say so, in a notice at the top of the result
  block. The stream path had never read `finish_reason` at all: only the non-streaming path — used
  solely by the "test connection" button — reported truncation, while translate and explain, the
  ones people actually use, are streaming. Two optional SSE events were added
  (`input_truncated` / `truncated`; see `docs/API契约.md`). Separately, `HTTPError` is now caught
  ahead of `URLError` and its body is read, so an upstream 400 that says "max_tokens must be
  <= 8192" reaches the user instead of a bare `HTTP Error 400: Bad Request`.
- **Text you could read but not select or copy**, in the packaged app: the `req_xxxxxx` id at the
  top of the detail view, the settings page's paths and BASE_URL, the data directory and log path in
  About. Selectability was an **allow-list** of CSS classes whose neighbouring comment already
  described the opposite intent ("interactive controls not selectable, body text always
  selectable") — so every display component added since missed the list. WebView2 gives no native
  context menu, and the self-drawn one bails out when it finds neither a selection nor a known
  block, which is why those elements had no copy path at all: not merely awkward, impossible. The
  rule is now a **deny-list** — body text selectable by default, `user-select: none` only on
  buttons, tabs, date chips, toggles and DAG nodes/lane heads — and the right-click "copy block"
  selector covers the crumb bar, settings rows, the About row and DAG nodes. Button labels
  ("← Back", "Open", "Check for updates") are stripped from a copied block.
- **Switching dates fast could leave the timeline on the wrong day's data.** `loadDag()`
  had no request guard, so two overlapping loads — one fired by entering the DAG view
  (`S.date` = today) and one fired a moment later by clicking a date chip (`S.date` = a
  historical day) — raced: whichever response landed second won, regardless of which date
  it was for. The observed symptom was a historical chip highlighted while the content area
  read "no captures for this date" (today's empty response had arrived last). The API data
  was never wrong; this was a pure frontend timing bug. `loadDag` now records the date and
  a monotonically increasing sequence number before the fetch, and discards a response whose
  date or sequence no longer matches. One subtlety the fix respects: the guard is taken
  **after** the first-load `fetchCaptures`, not at the entry — `fetchCaptures` itself sets
  `S.date` (null → today on a first visit), so a guard taken too early would discard the
  legitimate first load every time. Low impact in practice (you had to click fast, on two
  dates, with one of them empty); recorded when found, fixed before this release.

## v0.4.4 - 2026-08-01

### Fixed
- **Leave the app running past midnight and it stopped showing anything.** Reported as "the new
  day's captures are slow to appear"; measured, it is worse than slow — they never appear.
  `S.date` is only ever assigned by `fetchCaptures`, which runs on startup, on a date-chip click,
  and after a purge; **no timer re-fetches it** (the 5-second interval only refreshes the status
  card). So once the clock rolls over, `S.date` is stuck on yesterday, and the guard at the top of
  the live-update handler — correct in itself, it stops today's traffic being added to a historical
  day's totals — **silently discards every capture of the new day**. The date chips come from the
  same response, so today never even gets a chip to click. Reproduced in a browser: with `S.date`
  set to yesterday, a pushed capture leaves the list at 18 rows and never reaches the DOM. There is
  now a `followToday` flag (set from whether the fetched date *is* today) and a rollover check on
  the existing 5-second poll, plus one on the live path so a busy day switches immediately instead
  of waiting for the next tick. Picking a historical date deliberately sets `followToday` false —
  the rollover must never yank someone off a day they chose. Separately, the currently viewed date
  is now always present in the chip row: on a fresh day the jsonl does not exist yet, so
  `dates_available` omits today and the selected state pointed at a chip that wasn't there.
- **Small text was below WCAG AA, which is what "the font looks blurry" actually was.** Reported on
  a 2K display at 100% scaling. Measured against the relative-luminance formula (AA wants 4.5:1 for
  small text): `--apple-secondary` `#9C9489` was **3.00:1** on a white card and is used 29 times —
  including `.cap-time`, the 11 px timestamp column of every list row — and `--text-faint`
  `#B0A892` was **2.37:1**, used 16 times including `.cap-ttft` (10.5 px) and `.thinking-text`
  (11.5 px italic). A 2.37:1 ten-and-a-half-pixel italic does not read as "low contrast" to anyone;
  it reads as blurry, and more so the denser the display. The warm-grey ladder is re-cut to pass on
  **both** the white card and the `#F4F2EF` soft background while keeping its four tiers distinct
  (7.27 / 6.32 / 5.65 / 5.17 on white) and the same hue. Only the four variable definitions changed
  — the 45 usages were untouched, which is the whole point of having had them as variables.

### Added
- **Interface scale (90%–200%) in Settings → Interface**, applied and saved immediately, like the
  language switch. Every dimension in the stylesheet is an absolute px, so on a 2K/4K panel at 100%
  system scaling the text is genuinely small and until now the only remedy was changing the *system*
  scale, which affects every application. Implemented with CSS `zoom`, deliberately **not**
  `transform: scale()` — the latter is a bitmap scale and would make the text blurry, which is half
  of what this setting exists to fix. The value is clamped to 80–200 on both read and write:
  the frontend writes it straight into `zoom`, so a 0 or a stray large number would leave a window
  you cannot open the settings page in to undo it.

### Changed
- **The failure-grouping panel is no longer a banner on the first screen.** Added one release ago
  directly under the status card, it sat at the visual weight of an *alert*, alongside "recording
  failed to reach disk" and the config-check errors. It is not an alert — it is a summary you reach
  for **when investigating**; the failures themselves are already visible as red rows in the list.
  Putting a summary where an alert goes costs twice: it takes first-screen height away from the
  actual content, and a banner that is present every day drags the real alerts down with it into
  being ignored — the same mechanism the config check's own rules warn about ("after the second
  false alarm nobody reads the banner again"). It is now a small button in the date row's tool area
  next to *Clear* — `● 2 failed · 2 groups`, not rendered at all when the day has none — and the
  panel opens in place below it. The first screen goes back to: status card → real alerts, if any →
  date row → **the capture list**.

## v0.4.3 - 2026-08-01

### Added
- **Failure grouping finally has a way in from the UI — the gap this project had been calling its
  largest for six weeks.** The backend has compressed a bad day's failures into a handful of groups
  since 2026-07-25 (measured: 2,719 failures → 7 groups in 0.09 s), and until now the only ways to
  see that were the HTTP API and a source-only CLI subcommand. Anyone using the app as an app saw a
  wall of red rows and no explanation. The capture view now carries a fold under the status card —
  *"N failures today → M groups"*, not rendered at all when the day has none — and each group is one
  card: the count, the error kind and status, which request kinds were hit (`title×19` breaks
  session naming and nothing else), **the upstream's own error sentence**, the request-side fields,
  and sample ids that jump straight to the record. The request-side fields keep the distinction that
  *is* the diagnosis: a **bold** field was identical across the whole group (a candidate cause),
  a bracketed list spans several values (that field is ruled out). The frontend only renders — the
  grouping rules stay solely in `diagnose.py`, because a second implementation is a second thing to
  drift. Live updates re-fetch only when the incoming batch actually contains a failure, so a day of
  successful traffic doesn't turn a summary panel into an 800 ms full scan.
- **The binary now carries its own manual, so an agent on someone else's machine can learn to drive
  it.** `docs/AI_USAGE.md` is thorough, and it lived only in this repository — while what people
  download from Releases is a single executable. An AI on that machine had all three routes closed:
  `--help` printed nothing (and, worse, **opened the GUI**), the binary shipped no documentation,
  and the running service had twenty `/api/*` endpoints but not one that answered "what are you and
  how do I use you". Three small changes close it: the guide is packed into the build (`datas`),
  `GET /api/ai-guide` returns it as Markdown **prefixed with this machine's runtime facts** (real
  listening port, absolute data paths, whether it is currently recording — the document says
  `~/.cc-wire-analyzer/` and "the port starts at 5051 and moves up", which is not what a caller can
  act on), and `cc-wire-analyzer --help` prints the same text and exits without a window. Settings
  gains a **For AI agents** card with one copyable sentence — "this machine is running CC Wire
  Analyzer, read `http://127.0.0.1:<port>/api/ai-guide` and drive it from there" — which is the one
  hop that was missing between *the user has the app* and *their AI knows how to use it*. If the
  document is missing from both the bundle and the repo, the endpoint falls back to a built-in
  cheat sheet rather than erroring: output to an agent may be short, but it may not be an error page.
- **A documented platform limit turned out to be wrong, and it had cost three weeks of
  discoverability.** `desktop.py`, `docs/AI_USAGE.md`, `docs/开发指南.md`, `docs/架构总览.md` and
  `docs/问题域手册.md` all stated that a noconsole binary "has no stdout, so CLI subcommands can't
  print anything" — the stated reason for having no `--help` at all. Measured: noconsole means no
  *console is allocated*, so a double-clicked process indeed has nothing to write to; but when a
  shell starts it **through a pipe or a redirect** — which is exactly how every agent harness runs a
  command — fd 1 is a valid handle and `os.write(1, …)` works. Verified across bash pipe, PowerShell
  pipe, `cmd /c … > file` (all print), `$out = & exe --help` (empty — PowerShell not waiting on a
  GUI-subsystem process, unrelated to stdout) and double-click (nothing, which is why the guide is
  also written to `<data dir>/ai-guide.md`). The conclusion that HTTP is the right channel for
  agents still stands and the full CLI stays unpackaged; what changed is that the *reason* is no
  longer a false claim that quietly blocked the most natural entry point. The five documents now
  carry the measurement matrix instead of the assertion.
- **The detail view now shows the two usage fields CC reports that we were dropping.** Every
  response from a third-party gateway carries `server_tool_use` (with `web_search_requests`) and
  `service_tier` inside `usage`; we recorded them verbatim, but `usage_norm` and the detail panel
  surfaced only input/output/cache_read/cache_creation, so the server-side tool-call count and the
  service tier were invisible. The Usage card now appends a `tier:` / `web_search:` line straight
  from the raw `resp.usage` (not the normalised short names). `web_search_requests > 0` is exactly
  the signal that server-side web search happened — a radar for the next blind spot. Surfaced by
  the capability audit; the 260731 protocol audit had no such traffic to see it.
- **The protocol-extensions panel now folds, collapsed by default.** It was a flat chip row occupying vertical space; it now folds like the other sections and starts collapsed, with the extension count (and any unknown-extension warning) in the summary, so the "new extension = next blind spot" radar survives being collapsed.
- **Response headers are collapsed by default again.** v0.4.0 had opened them so the wire-only fields (ratelimit / request-id) weren't hidden; with the protocol-extensions panel now surfacing the capability radar on its own, the response headers demote back to collapsed (wire fields still bolded when expanded).

### Fixed
- **A failed request could still show a green dot in the capture list.** The row's status dot only
  went red when there was an error *and* the status was absent or ≥ 500 — which was true until this
  release added `stream_error`, an in-stream failure that keeps HTTP 200. Such a row landed in the
  2xx branch and got a **green** dot, in the same release whose own note says consumers must judge
  failure by `error`/`has_error` and never by status alone. Any `has_error` row now takes the error
  colour; 4xx keeps its own shade, since "the upstream refused" and "the request blew up" are worth
  reading apart.
- **The detail view called every non-streaming response an SSE stream.** The header chose between
  "SSE · N chunks" and "non-streaming" on `resp.chunks_count != null`, while `_finalize` writes
  `chunks_count` for *every* response (it is the body's chunk count, 1–4 on a plain reply). The
  condition was therefore always true and the "non-streaming" label had never once rendered on real
  traffic — every security-classifier and count_tokens response, all non-streaming, was mislabelled.
  Not cosmetic: "the security classifier is non-streaming" is the premise behind several pieces of
  this project's logic (the non-streaming parse path is where the 260713 usage loss and the 260731
  brotli blind spot both came from), and the UI was stating the opposite. It now reads the request
  body's `stream` field — truthily, because real non-streaming requests **omit** the key rather than
  sending `false`.
- **Switching language left the config-check and failure-group items in the old language.**
  `setLang` re-rendered the status card, the date row and the capture list, but those two panels are
  built in JS and only their static labels carry `data-i18n` — so the drawer contents stayed put
  while the rest of the interface changed.
- **The macOS build spec had drifted from the Windows one and would have shipped a bug that was
  already fixed.** `build.spec` lists `brotli` / `zstandard` in `hiddenimports` (added this release,
  after a missing brotli caused every security-classifier response to record empty); `build-mac.spec`
  never got them. Both specs now carry the same list — and the same `docs/AI_USAGE.md` data entry.
- **Capability-side recording audit: run, and one documentation posture fixed.** The 260731 audit
  was *protocol-side* (what CC declares). This runs the other half — *capability-side*: spawn a
  real `claude -p` for each CC ability (tool calls, parallel tools, thinking, subagents, vision)
  through the proxy and check the recording parses it. 14 captures across 7 dimensions;
  **core parsing had zero hard bugs** — tool_use/tool_result, parallel tool_use in one response,
  thinking blocks with signatures, subagent identity (`cc_is_subagent` + `x-claude-code-agent-id`,
  zero counterexamples again), the spawn edge (including multi-level A→B→C nested subagent chains), and base64 image blocks were all recorded and
  classified correctly. The Workflow tool's subagents are recorded too, but their spawn relation does not resolve — prompts live in a dynamic JS template literal inside `input.script` (`${VAR}` runtime-interpolated), invisible to the wire layer; the trigger edge stays unresolved by design (see issue A6), but the fallback lane now keys on `agent-id` (instance-level) instead of the type-level `agent_fp` fingerprint, so Workflow's parallel subagents at least split into separate columns instead of merging into one. `issues/closed/260801_能力面录制盲区审计.md`. The audit did surface one
  documentation P0: the "isolated capture" posture in `CLAUDE.md` / `docs/开发指南.md` §5 /
  `tools/lane_probe.py` claimed `ANTHROPIC_BASE_URL=… claude -p` works because "process env takes
  precedence over settings.json". It does not — CC 2.1.220 ignores the process-level var (a dead
  port still connects straight through, records nothing, raises no error; reproduced in bash and
  PowerShell), so anyone following the docs silently captured nothing. Fixed to `claude -p …
  --settings '{"env":{"ANTHROPIC_BASE_URL":…}}'`, with a note on *why* the process env fails.

- **A tool-call turn no longer shows a blank summary in the capture list.** `index_record` took
  the response's first text block as the summary, so a pure tool-call turn (thinking + tool_use,
  no text — subagent middle steps, tool loops) left the list row empty; the list (`_public_summary`)
  had no fallback while the DAG (`_node_summary`) fell back to `last_user`, so the two disagreed.
  The summary now falls back to the first tool_use's name (`🔧 Glob`, `🔧 Agent`) — that describes
  what the turn *did*, which is what the summary is for. `IDX_SCHEMA` 6→7 so old captures rebuild
  with the fallback (~5 s/day, jsonl untouched). Verified on real captures: two previously-blank
  rows now read `🔧 Glob` / `🔧 Agent`.

- **A failed request was being recorded as a successful one.** When an upstream reports an
  error *inside* the SSE stream, the HTTP status is still 200 — the error rides in an
  `event: error` frame. Our SSE parser had no branch for it, so the frame was skipped, no
  `error` was written (only `status >= 400` wrote one), and the request went into the
  recording as a **success** that merely happened to have no content. The damage was never
  limited to the single record: failure grouping keys off `has_error`, so in-stream errors
  have never entered the failure statistics at all — **we have been under-reporting the
  upstream failure rate**, and an observability tool that under-reports errors is worse than
  one that reports none. Both of the paths CC's own SDK throws on are now recognised (the
  `event: error` frame name, and `type == "error"` in the data), recorded as a new error kind
  `stream_error` with `status: 200`. **Consumers must judge failure by `error`/`has_error`,
  never by status alone.**

- **Decompression and decode failures now leave a trace instead of a blank.** Previously a
  failure meant `body_text` / `usage` / `content_blocks` all silently went missing, with
  nothing on screen to say why — it looked like the upstream had returned nothing. The
  response now carries `decode_error` (`missing_codec:br` / `unknown_encoding:…` /
  `decompress_failed:…` / `utf8_decode_failed`) and the detail view shows it. An encoding
  outside the list CC advertises is now reported rather than passed off as plain text.

- **Context-compaction blocks and the matched stop sequence are recorded.** `compaction_delta`
  is aggregated into a `compaction` block (CC advertises the `context-management-2025-06-27`
  beta and 3,488 of 4,652 sampled requests carry a `context_management` field — this is a
  feature in active use, and when compaction happens is exactly what the wire layer should
  reveal). `message_delta.stop_sequence` is kept as `response.stop_sequence`: 200 responses in
  the sample ended on a stop sequence without our ever recording *which* one, and that value
  is what explains why the body cuts off where it does (the security classifier's truncated
  `<severity>8` is this mechanism at work).

  These three came out of a full audit against what CC itself declares — request headers,
  request body fields, and the SSE accumulator branches in CC's own source. The method is
  written up in `docs/开发指南.md` §2.5, and generalised for other harnesses as unit 0 of
  `docs/问题域手册.md`. Verified by new `proxy_selftest` cases `[3d]`/`[3e]` (an error frame
  must be recorded as a failure *and* reach failure grouping; a compaction block must
  aggregate and not be judged a failure) and four new `dev_seed` samples. The audit also found five suspected gaps that turned out to be
  non-issues, and one dead i18n key (`ek.parse`, a kind the code never produces — the v0.4.3
  doc pass fixed the contract but left the key) which is now gone.

- **What CC declares about itself is now recorded and surfaced.** Every request carries an
  `anthropic-beta` header listing the protocol extensions CC has enabled (18 distinct features
  across the sample, in 18 combinations, drifting with CC's version) — it was buried in one
  long comma-separated line inside a collapsed Headers panel, where nobody would ever read it.
  It now renders as its own row of chips, with anything outside the known baseline highlighted
  and called out: **a newly enabled capability is how you find the next recording blind spot**,
  usually before the unfamiliar field or response block shows up. The index also keeps
  `context_management` / `diagnostics` / `stop_sequences` / `thinking.budget_tokens`, which CC
  actively uses and we had never parsed (`IDX_SCHEMA` 5 → 6).

- **`signature_delta` and `citations_delta` are aggregated** — a thinking block's signature
  (assignment) and a text block's citations (append). The two accumulate differently; both
  follow CC's own accumulator rather than what looks reasonable.

- **`x-claude-code-agent-id` is recorded as a cross-check on subagent identity.** It agrees
  with the billing-header flag in all 225 subagent requests across 4,629 sampled captures,
  with no counterexample, and carries per-instance resolution. **The identity verdict itself is
  unchanged** — one more agreeing signal is not grounds to overturn a measured finding. Worth
  noting for the open identity question: those 225 were all `cc_entrypoint=cli`, the mode that
  had never been measured. That is statistical evidence from historical captures, not the
  hand-verified capture the question actually calls for, so the question stays open.

- **Recording now covers every compression format CC advertises** (`Accept-Encoding:
  gzip, deflate, br, zstd`). DeepSeek compresses non-streaming responses — exactly the
  security-classifier requests — with brotli; without the `brotli` package the proxy logged
  the compressed bytes and the recording dropped `body` / `usage` / `content_blocks`
  entirely (every security request showed up empty). Added `brotli` + `zstandard` deps
  (their C extensions also go into `build.spec` hiddenimports) and a zstd branch in
  `_decode_body`. `proxy_selftest` gains a `[3c]` case: a mock upstream returning
  `Content-Encoding: br` must round-trip transparently to the client **and** be decompressed
  into the recording. `dev_seed` gains an O4 DeepSeek-shaped security sample.
  See `issues/open/260731_安全分类器响应丢失_brotli压缩盲区与harness分析不足.md`.
  *(Fix authored by Claude Code session `d61ee348` — actual upstream model
  deepseek-v4-flash[1M] — on 2026-07-31; real-traffic verification still pending because the
  security classifier kept failing while the fix was verified.)*

- **The version the app reports now always matches the release tag.** The version had been
  hand-copied in three places (git tag, `src/app.py:VERSION`, `pyproject.toml`) with nothing
  keeping them in sync, so releases shipped showing the wrong version — v0.4.2's exe still
  reported v0.4.1 in About. The tag is now the single source of truth: CI generates
  `src/_version.py` from the tag before building (the `Inject version from tag` step in
  `release.yml`), `app.py` reads it with a `dev` fallback for local runs, and `pyproject.toml`
  is synced in the same step. The convention in `docs/开发指南.md` §9 is widened from "no
  version in README" to "no hardcoded version anywhere".

- **Documentation consistency pass.** A multi-agent audit caught 26 instances of drift accumulated
  since v0.4.0: the six-way recovery list had diverged between the dev guide and the architecture
  overview (the dev guide misnamed the sixth path as "CLI restore"), the API contract listed a
  phantom `parse` error kind the code never produces, `IDX_SCHEMA` was documented as 4 (actually
  5), idx field lengths and the i18n key count (245, not 225) were stale, and CONTRIBUTING still
  hardcoded port 5051. Fixed across 12 files; the §9 "no hardcoded version" rule and the
  doc-maintenance strategy's SSOT pointers were tightened at the same time.

## v0.4.2 - 2026-07-30

### Fixed
- **The two columns of the detail view line up again.** Moving `model` / `stream` to the request
  side in v0.4.1 left them as a bare chip row (21 px tall) facing the response side's meta **card**
  (46 px) — so from the second block down, **every card in the two columns was 27 px out of step**.
  The request side now has a card of its own, and `stream` always states `true`/`false` instead of
  vanishing when false (non-streaming is exactly what count_tokens and security requests are).
  Measured across five request kinds (main / compact / security / title / error): both columns'
  first three blocks now share identical y positions to the pixel. Chips also carry a transparent
  1 px border now, so a bordered chip no longer sits 1 px taller than a solid one — that alone had
  the two columns 1 px apart on error captures.
- **The capture list is now a real table.** It was a flex row, so whether a row had a kind chip
  (48 px) and how long its model name was (`glm-5.2` vs `glm-5v-turbo`, 32 px) shifted every column
  after it: measured across 13 rows, the summary column started anywhere from 452 px to 753 px.
  It is now a fixed-column CSS grid — every column starts at the same x on every row, in all three
  languages, at both the 1080 px minimum window and full width. Long paths and model names ellipsize
  with the full value on `title`. Column widths are sized for the **longest** language, not Chinese
  (Japanese `エージェント` and `初回応答 550ms` were being cut mid-glyph).
- **Timeline legend is left-aligned when it wraps.** `margin-left:auto` was meant to push the
  line-style legend to the right on wide windows; after wrapping it kept pushing, so lines 2 and 3
  hung off the right edge at ragged offsets (46 / 344 / 262 px).
- **Settings: the "open" button no longer breaks into two lines** and a long `settings.json` path no
  longer squashes its own label to 86 px across three lines. Buttons never wrap (`white-space:nowrap`);
  the label column has a floor and long values wrap instead.
- **Security nodes in the timeline now say what was being reviewed.** v0.4.1 fixed the list row but
  not the DAG, which still showed the response fragment (`<severity>8`,
  `<block>yes</block><category>…`) — the least informative summary available. The formatting is now
  a single shared helper, and `_node_summary` carries `sec_action` for security nodes only.

### Changed
- **Release assets use one naming scheme on both platforms**: `cc-wire-analyzer-windows.exe` and
  `cc-wire-analyzer-macos.zip` (was `CCWireAnalyzer-mac.zip`). The macOS bundle is renamed to
  `cc-wire-analyzer.app` as well, so the serve command reads the same on both:
  `cc-wire-analyzer.exe serve` / `cc-wire-analyzer.app/Contents/MacOS/cc-wire-analyzer serve`.
  Note for macOS users upgrading: the old `CCWireAnalyzer.app` in `/Applications` is not replaced —
  delete it yourself.

## v0.4.1 - 2026-07-29

### Added
- **Security reviews now say what was being reviewed and how it was judged.** Claude Code runs a
  background security classifier on the agent's actions — on a busy day it is one request in six
  (measured: 59 of 388, and 175 of 510 on another). The recording had all of it, and the UI showed
  none of it: the request renders as a ~108,000-character collapsed `system` block plus 170-odd
  flat `messages` blocks, so **the action actually under review is the 174th block** and you have
  to scroll to it; the list row meanwhile summarized the response as `<block>yes</`, the least
  informative 80 characters available. Three things are now surfaced, parsed once in
  `classifier.py` (`sec_request` / `sec_verdict`) and only rendered by the frontend:
  - **What is being judged** — the last block of the transcript, i.e. the command CC was about to
    run, as tool + argument. The list row now reads `reviewing PowerShell · Set-Location …`
    instead of a fragment of the answer.
  - **How it was judged** — a chip carrying either the `severity` score (0-100, **50 is the
    allow/block boundary**) or the block/allow verdict, with the matched rule name and the
    upstream's stated reason in the detail card. Parsing matches on the opening tag only:
    responses end on `stop_reason=stop_sequence`, so the real wire text is a bare `<severity>8`
    with the closing tag eaten — requiring balanced tags would have failed on 100% of real traffic.
  - **What the review sent upstream** — the rule base (~108 KB), **your CLAUDE.md in full**
    (~14 KB, sent as "context about the user's environment and intent"), and how many prior actions
    of the transcript went with it. This is exactly the kind of fact only a wire-level view can
    state.

  Measured against real captures: `sec_request` parsed 59/59 and 175/175, `sec_verdict` 56/59 and
  172/175, with zero false positives on 120 sampled non-security requests. The six that produced no
  verdict were checked rather than waved off — three were upstream timeouts, and **three were the
  model ignoring the required output format**: asked to `Respond with <severity>N</severity> ONLY.
  No other text.`, it began writing prose about the action and hit its 64-token ceiling, so that
  review reached no conclusion at all. The card says so explicitly (`no verdict`, with the
  `stop_reason`) rather than rendering blank — a security check failing silently is precisely the
  kind of thing this tool exists to make visible. Index schema bumped 4 → 5 (the action lives at
  the *end* of the transcript, past the 2,000-character `last_user` cutoff), so indexes rebuild
  once on first access (~5 s for an 866 MB day, ~7 s for 1.18 GB; the jsonl is untouched).
  `dev_seed.py` gained all three verdict shapes — its old security sample had a shape that does not
  occur in reality, so none of this path would have been exercised by UI self-tests.
  See issues/closed/260729_安全审查可读性.md.
- **[docs/报文解读.md](docs/报文解读.md)** — a user-facing guide to the 7 request kinds CC sends
  (main / subagent / title / compact / security / count_tokens / other): what each one is, its payload
  shape, why CC sends it, how to recognize it, and the common confusion points. Includes a "don't trust
  surface features" methodology section (count_tokens and security look alike on stream/output but are
  unrelated) and the system three-block explainer. Cross-linked from 界面导览 / 架构总览 / 文档维护策略.
- **Check for updates** in the About panel — fetches the latest GitHub release and compares versions
  (12s timeout, degrades to a manual-link hint on network failure).
- **System blocks now show their role** in the detail view — each `system[i]` chip is annotated by content
  (billing header / identity / security rules / compact / title), so e.g. a security request's ~108K-char
  `sys[1]` is visibly labeled "Security rules" instead of being an inscrutable collapsed block.

### Changed
- **Capture list now shows a kind chip for non-main rows.** main threads stay unmarked; the others get a
  chip (计数 / 安全 / 标题 …) so a row's role is visible at a glance. Backend `_public_summary` now carries
  `kind` (computed via `classifier.classify_idx`).
- **Backup count moved from the capture status card to the Settings panel.** "备份 N 份" in the capture
  header was contextually odd; it now shows under Settings → 备份目录 ("当前 N 份").
- **ttft label localized** (zh 首字时间 / en ttft / ja 初回応答) in the list row and the detail header.
- **Detail-panel field placement fixed**: `model` and `stream` come from the request body, so they moved
  from the response meta-row to the request side. The response meta-row now keeps only response-origin
  fields (status / stop_reason / ttft / total) — `model` was never server-returned; this tool records no
  response model field.
- **Request-side thinking blocks** now render with a chip + bigText toolbar (translate / explain),
  matching the response side. (CC usually omits thinking from request history, so this mainly matters
  when it doesn't.)

### Fixed
- **Hiding a main lane now also hides its auxiliary calls.** Closing a main lane in the timeline used to
  leave its title / security / count_tokens / compact calls visible in the shared aux column with no sign
  of whom they belonged to. Aux nodes whose `near`-edge parent lane is hidden now hide too, an emptied aux
  column no longer reserves space, and the lane menu carries a hint explaining the linkage.
- **Removed the estimated cost (≈ ¥x · PRICING) from the response panel.** It was computed from official
  list prices, which are wrong for users on third-party gateways (the common case for this tool's
  audience). The raw Usage token counts remain.
- **A role hint that could never fire, and a classification error nothing would have reported.**
  Post-v0.4.0 code review, each finding checked against real captures rather than reasoned about:
  - The detail view's system-block role hint carried a `compact` rule matching on
    `summarizing conversations` / `summary of the conversation`. Measured on real compact requests
    (07-26 `req_fbab1f0` / `req_c012395`): their `system` is the ordinary main-thread prompt
    (`You are an interactive agent…`) and the compaction instruction sits in the **last user
    message** — which is what the classifier keys on too. So the branch, and its three
    `sysRole.compact` strings, could never render. Removed, with the measurement written into the
    function's comment so it does not get re-added on intuition.
  - `_public_summary` degraded a failed `classify_idx` to `kind: "other"` with no log line. A change
    to the index fields would have turned a whole day's capture list into `other` with nothing
    anywhere to notice it by — the project's own recurring bug type ③. Now counted and logged like
    the existing write/index failure counters, and bounded (first occurrence, then every 100th)
    because the function runs once per list row and real failures come in sheets.
  - Nine dead i18n keys removed, left behind by earlier removals: `detail.usageNote` (the dropped
    cost estimate), `status.backups` (the relocated backup count), `row.probe` (superseded by
    `kindLabel`). The three language tables are now key-for-key identical at 245 entries each.
    The `.cap-row.probe` CSS class keeps its historical name — it is now driven by `isAux` (any
    auxiliary call, not just token probes) — with a comment saying so.

  Verified: all six self-tests green; `kind` measured at 0.033 ms/row and computed only over the
  paged window (the DAG path does not use `_public_summary`), so no regression; the frontend
  re-checked in a browser against a 510-record day in an isolated `CCWA_HOME` — kind chips, system
  role labels in all three languages, no raw keys leaking, and lane-hiding still taking its
  auxiliary nodes with it (56-node main lane hidden → 78 nodes gone).

### Docs
- **The documentation is now organised by what you're trying to do, and the development
  conventions have exactly one home.** The `docs/` folder had grown to six files without anyone
  asking what set of jobs it was supposed to cover. Answering that question surfaced a defect
  worse than any single stale sentence: **the project's development conventions existed in three
  places at once** — `CLAUDE.md` (local, not in this repo), `CONTRIBUTING.md` (a public summary),
  and four chapters of `docs/架构总览.md`. Two of those were copies, and both had drifted.
  `CONTRIBUTING.md` listed 2 self-tests when there were 6, listed 3 safety invariants when there
  were 8, and stated twice that "the dev server reads templates live, no rebuild needed" — which
  is false (Jinja caches templates under `debug=False`), and which actually misled someone on
  2026-07-29 into debugging a cached page for half an hour. `docs/架构总览.md` carried a second,
  fuller copy of the invariants plus the recurring-bug table and the module dependency tree, and
  its further-reading appendix cited counts that no longer matched anything.
  - **New: [`docs/开发指南.md`](docs/开发指南.md)** — the single source of truth for conventions:
    eight safety invariants each paired with what it prevents, the four recurring bug types with
    their first occurrence and their recurrence, the defensive-design table, the subagent-identity
    ruling, all six self-tests, the frontend rules, the module dependency tree, and the
    issue-first workflow. It was **migrated, not rewritten** — putting a fourth copy into the
    world would have been the very disease being treated. `docs/架构总览.md` keeps the
    architecture narrative (five layers, data flow, evolution, design philosophy) and now links
    here for the rules; `CONTRIBUTING.md` is a thin shell covering setup, building and the PR
    checklist, and stopped restating anything.
  - **New: [`docs/问题域手册.md`](docs/问题域手册.md)** — for building the equivalent tool for a
    different agent harness (Codex CLI, opencode, a bespoke agent). This is the one thing the
    existing docs could not answer: `docs/架构总览.md` explains how *this* project is built,
    which is the wrong layer for a port — `proxy.py` becomes irrelevant, while every problem it
    solves remains. Distilled from 45 archived iteration records plus this changelog, it covers
    nine capability units (non-invasive config takeover / lossless recording / request attribution
    / semantic classification / indexing at volume / timeline visualisation / diagnosis /
    dual-mode consumption / desktop packaging). Each unit states the problem, why the naive
    approach fails, the ruling, and **which conclusions survive a change of harness**. Every
    "naive approach" listed is one this project actually shipped and had to undo. The headline
    finding: only two of the nine units are harness-specific, and they are exactly the two that
    can only be settled with real traffic and human ground truth — the ones that cost this
    project twelve days.
  - **[`docs/界面导览.md`](docs/界面导览.md) is now only about using the app.** Its "layer three:
    optimisation opportunities" chapter (about 150 lines) was a development backlog living inside
    a user guide, and it had gone stale — three of its twelve entries were already implemented,
    while the P0 it described is still open. Removed; the surviving entries were re-verified
    against the code and moved out of the published docs.
  - The four development-facing documents now differ by **when you reach for them**: understand
    the project → 架构总览; about to change code → 开发指南; changing the docs → 文档维护策略;
    building the same tool elsewhere → 问题域手册. That criterion (same audience, different
    trigger) was added to `docs/文档维护策略.md`, along with two new rot entries and a
    strengthened lesson: the "prescription that itself rots" pattern has now been observed three
    times (the hand-written README version line, the CONTRIBUTING summary, the architecture
    chapters), and the test for it is simply **is this content written down in a second place?**
- **The READMEs now open with when you'd want this, a case where it paid off, and what it does
  with your traffic.** The repository has been public since 2026-07-12, and the landing page led
  with its technical category — `MITM proxy`, `wire-level`, `SSE`. That is clear to someone who
  already knows they need a packet capture, and opaque to a Claude Code user who does not yet
  know which of their own bad afternoons this addresses — while "MITM" plus "records everything"
  raises an entirely reasonable question about whether it is safe to point a session at it. All
  three READMEs (en/zh/ja) now open with three sections instead:
  - **When you'd reach for this** — three situations to recognize yourself in (CC going through
    a third-party gateway when something is off; wanting to see what CC actually transmits —
    system prompt as sent, spawned subagents, background security-classifier calls, upstream
    token counts; wanting a session on record to go back through). It also says who should
    *not* bother: if you are on the official endpoint, nothing is wrong, and you want
    conversation history, `~/.claude/projects/*.jsonl` already has it and reads better.
  - **A real example** — the effort/400 finding from v0.4.0, end to end: session titles silently
    not generating, every title request coming back `400`, the upstream's own sentence naming
    the field, the root cause (`effortLevel: low` in `settings.json` overridden by
    `CLAUDE_CODE_EFFORT_LEVEL: max` in the environment), and how it became two rules in the
    config check. Real redacted capture data, no mock — and it states plainly that the tool
    fixes nothing for you; it shows what happened and names the field.
  - **Is it safe to point your traffic at it?** — four points: no recording leaves the machine
    (with the app's own outbound calls listed explicitly), one config field edited and restored
    on exit, credentials redacted but bodies stored verbatim so captures are sensitive files,
    and how it coexists with official-direct / third-party / cc-switch setups.

  The screenshots moved up to sit right after the first section, since three new prose sections
  had pushed them three screens down. See issues/open/260725_公开README入口与信任表达.md — the
  remaining item there (a release kit for a target community) is deliberately left undone: it is
  an outward-facing action and stays the maintainer's call.
- **The README no longer carries a hand-written version number.** v0.4.0 added a
  `Current version: vX.Y.Z` line to all three READMEs because GitHub's rendered README does not
  show the current tag. **That line went stale at the very next release** — v0.4.0 shipped while
  all three READMEs still said v0.3.2, and it took three independent doc audits to notice. The
  fix was itself the rot: a version number's single source of truth is the git tag, so a copy in
  the README is guaranteed to diverge, and "edit one line in three files on every release" is an
  obligation nobody keeps. The line and its maintainer note are gone; the header keeps
  `Releases · Changelog` links, and GitHub points the first one at the latest release for free.
  The general lesson, now recorded in [docs/文档维护策略.md](docs/文档维护策略.md): **a remedy for
  documentation rot that needs periodic human syncing is itself the next piece of rot** — prefer a
  zero-maintenance pointer over a maintainable copy.
- **`docs/AI_USAGE.md` translated to Chinese, and the en/ja READMEs now flag which docs are
  Chinese.** The deep-dive docs are written in Chinese; the English and Japanese READMEs linked
  them without saying so, leaving a reader to discover it by clicking. Each link is now marked
  (ZH), with a line suggesting machine translation. A full multilingual docs policy is deferred to
  its own release.
- **`docs/API契约.md` corrections and one dead field removed from the code.** The `start` response
  documented (and returned) `orphan_recovered`, permanently `null` — the frontend only ever reads
  `orphan_recovered_at_startup` from `/api/proxy/status`. Field dropped from `src/app.py` and the
  contract; error-code enumerations for `start` corrected against the code, and a non-existent
  `parse` value removed from `err_kind`.

## v0.4.0 - 2026-07-28

### Changed
- **UI readability pass — translate technical enums and surface wire-only headers.** Three small
  UX improvements from the audit-driven optimization list ([docs/界面导览.md](docs/界面导览.md)
  P1-P2). `stop_reason` (`end_turn`/`tool_use`/…) and `err_kind` (`upstream_4xx`/…) now render
  through i18n lookup tables (`stopReasonLabel` / `errKindLabel`, mirroring the existing
  `kindLabel`), with zh/en/ja coverage and English fallback — non-programmers no longer see raw
  Anthropic API enum values. Response headers panel is now **open by default** (was collapsed)
  and wire-only fields (`anthropic-ratelimit-*` / `request-id` / `anthropic-organization-id` /
  `x-should-retry`) are bolded with a hint line "only visible at wire layer, not in CC's jsonl"
  — the project's own code comments call these "the most valuable information at the wire
  layer"; the collapsed state was hiding them from anyone who didn't know to look. Verified
  lane head already uses "Session N" numbering. See issues/closed/260726_P1-P2_前端微调批次.md.

### Fixed
- **Parallel same-template subagent spawn no longer collapses into one lane.** When N same-type
  agents (e.g. 4 Explore) were spawned in one main response with templated prompts that shared
  their first ~120 chars (common opening + task description), the lane alignment matched all N
  first-user messages to `prompts[0]` and hashed them all under the same lane key — N agents
  ended up stacked on a single lane (visually: one color, one column). Root cause and fix in
  `classifier.py`: bumped `PROMPT_PROBE_LEN` 120→300 and `PROMPT_MATCH_LEN` 200→1000,
  `first_user_task` 600→1500, `IDX_SCHEMA` 3→4 (forces rebuild of stale v3 indexes on first
  access — ~5s/day for the maintainer's 866MB day, jsonl untouched, no data loss). The remaining
  edge case (first 300 chars still identical across prompts) is left to a future bidirectional
  matching strategy. See issues/closed/260725_并行同模板子代理泳道撞车.md.

### Docs
- **Catch-up: docs back in line with the code, plus three new guides.** A 7-perspective audit
  (frontend / backend API / data pipeline / recording core / shell & tests / evolution / design
  tradeoffs) surfaced 8 places where docs had drifted from code. Fixed:
  - `docs/API契约.md` — added missing `/api/health/config` and `/api/diagnose/errors` sections;
    rewrote `/api/translate` and `/api/explain` as SSE (described as non-streaming); documented
    the dual-track `usage` field names (raw JSONL = Anthropic full names, list/DAG API output =
    normalized short names via `classifier.usage_norm`); documented `lane_id` naming rules;
    removed dead `orphan_recovered` field on `start` and the deleted `redact_headers` config key;
    supplemented `write_errors` and `external_change` on `/api/proxy/status`.
  - `docs/AI_USAGE.md` — maintainer note on the dual-track `usage` names + sibling-doc links.
  - `README` × 3 (en/zh/ja) — added a "Current version" line and a docs navigation block.
  - `CLAUDE.md` — corrected the "dead config" lesson: all three (`retention_days` /
    `auto_start_proxy` / `redact_headers`) were fixed in 260713 (first two wired up, third
    deleted along with its UI toggle); kept as historical reference.
- **Three new docs added**: [docs/界面导览.md](docs/界面导览.md) (human-audit view of all 4 UI
  screens + 13 prioritized UX optimization opportunities), [docs/架构总览.md](docs/架构总览.md)
  (5-layer architecture + data flow + evolution主线 + design philosophy + 8 invariants),
  [docs/文档维护策略.md](docs/文档维护策略.md) (meta: 5 strategies for keeping docs from
  diverging again, with a 12-item current-rot list). "Self-check sentences" appended to major
  sections of each core doc ("if you change X, also update Y/Z") make the maintenance policy
  actionable.
- **CLAUDE.md restructured for clarity.** The local AI-onboarding file had accreted ~1700 words
  of release-by-release narrative inside a single "current status" bullet, with the
  repeated-bug-types lesson and the subagent-detection rules buried in the overview instead of
  under "developer conventions" where they belong. Reorganized along the workspace's three-section
  skeleton (overview / background / conventions): overview slimmed to four bullets, the four
  recurring bug types pulled into a table, subagent rules given their own section, the
  architecture sketch redrawn as an ASCII tree, the macOS-real-machine status corrected to
  "260714 green". No facts removed — only relocated and rephrased. See
  issues/closed/260726_CLAUDE_md_结构整理.md.
- **Chinese changelog rephrased into a more formal register.** `CHANGELOG.zh.md` had carried over
  the conversational, first-person tone of the English original ("a bad day", em-dash asides,
  colloquial verbs) plus a few Anglicisms ("surface" → 抬出, "the complaint" → 抱怨,
  "in a way that" → 以…的方式). Rephrased throughout into standard written Chinese while keeping
  every fact, figure, code identifier, path, link, and the document structure unchanged. English
  `CHANGELOG.md` is unaffected. See issues/closed/260726_CHANGELOG_zh_风格改正式文档腔.md.
- **Project Overview section added at the top of the changelog.** The AI-onboarding
  snapshot (position / current status / next steps) used to live in the local CLAUDE.md;
  it now opens this file so anyone landing on the changelog sees the project's current
  state first. Rule-type key decisions stay in CLAUDE.md (developer conventions); a
  sanitized public navigation view lives here.

### Added
- **Failure groups — captured errors turned into something an agent can diagnose from.** A bad day
  fills the timeline with red cards and nothing more: 2719 failed requests in one measured day, all of
  them shown, none of them explained. Worse, the ones that matter get missed — the effort/400 finding
  in this release sat in the timeline for days and was only noticed while screenshotting something
  else. But a failed request is not noise: **the upstream already diagnosed it once**, naming the
  offending field and what to use instead. `GET /api/diagnose/errors` (and `cc-wire-analyzer errors`)
  groups a day's failures by error message — request ids and numbers normalized, so one root cause is
  one group — and puts the request side next to the complaint:

  ```json
  {"count": 2, "status": 400, "message": "output_config.effort 'max' is not supported when thinking is disabled …",
   "kinds": {"title": 2}, "samples": ["req_8421a7c", "req_1b66772"],
   "req_fields": {"model": "claude-opus-5", "effort": "max", "thinking": "disabled", "tools_n": 0}}
  ```

  `req_fields` carries the diagnosis: a **single value** means every request in the group had it, a
  **list** means the group spans several values. `effort: "max"` + `thinking: "disabled"` as single
  values identify the cause; `model: ["glm-5.2", "glm-5v-turbo"]` says the model is not what these
  failures share. `kinds` says which request types are hit — a failure confined to `title` breaks
  session naming and nothing else.

  Measured on the 2993-record day: **2719 failures → 7 groups in 0.09 s**, and the groups were
  immediately informative — 2650 upstream 504 timeouts, plus 19 `401 令牌已过期或验证不正确` whose
  `model` was `claude-fable-5`/`claude-sonnet-5`, i.e. official model names being sent to a
  third-party endpoint. Output is bounded (`limit`, default 20, `truncated` flag) because a single
  capture can exceed 5 MB and 2719 raw errors would bury an agent's context.

  This module only shapes data — **no LLM call, no analysis**. The reasoning belongs to the agent
  reading it, which is the same division of labour as the rest of the AI-facing surface.

- **Config check — a read-only doctor for "CC suddenly can't connect".** Switching back and forth
  between an official subscription and a third-party endpoint leaves configurations half-finished,
  and each half-finished state fails in a way that is hard to attribute: BASE_URL pointing at a
  third-party endpoint with no token (CC sends its subscription OAuth bearer there and is rejected),
  BASE_URL left pointing at a local port nothing listens on any more, expired subscription OAuth,
  effort settings the upstream rejects. None of these are bugs in this tool — but this tool is the
  only thing positioned to see them, since it reads `settings.json`, knows its own patch state, and
  watches the upstream's actual responses. Rather than keep patching the edge cases that
  half-switching produces, it now points the contradiction out before you start the proxy:

  - `GET /api/health/config` → `{ok, intent, patched, issues[]}`; `cc-wire-analyzer doctor` in the
    CLI returns the same payload for agents.
  - UI: a red banner for `error`, a yellow one for `warning`, and a **Config check** drawer listing
    every finding with the exact field, its current value, and what to change.
  - `POST /api/proxy/start` runs the check first and refuses with **409 `config_unhealthy`** on an
    `error`-level finding, so a broken config does not get a proxy layered on top of it (which is
    what makes these states so confusing to debug — `snapshot` would record the dead port as the
    upstream). `?force=1` overrides it, and the banner offers exactly that: the rules can be wrong,
    and the user knows their environment better than the rules do.

  Three constraints it is built under: **it never writes** to `settings.json` or credentials and
  offers no auto-fix (fixing configuration is the user's call, and "only ever undo the one change we
  can still prove we made" is a standing invariant of this project); it **prefers missing a problem
  to inventing one** (a false alarm is worse than a miss — after the second one, nobody reads the
  banner again); and it **never locks the user out**. Where a rule cannot tell two situations apart,
  it stays quiet: a loopback BASE_URL whose port *is* being listened on could be another instance or
  cc-switch, so it says nothing; during our own patch it reads the real upstream out of the marker
  instead of reporting its own address as a leftover; on macOS, where credentials live in the
  Keychain and the file genuinely does not exist, the OAuth rules skip silently instead of reporting
  "credentials missing".

  One of the eight rules came out of this release's own capture data rather than from design.
  Real recordings showed every session-title request failing:

  ```
  400 invalid_request_error: output_config.effort 'max' is not supported when thinking is
      disabled on this model. Use effort 'high' or below, or enable thinking.
  ```

  The maintainer's own config had top-level `effortLevel: low` and env
  `CLAUDE_CODE_EFFORT_LEVEL: max` — the env value wins, so session titles had been quietly broken
  with no sign of it in the CC interface. That is now two rules (`effort_level_conflict` for the
  contradiction, `effort_max_rejected_upstream` for the consequence), the second one gated on the
  upstream actually being the official endpoint, since third-party endpoints do not reject it.

### Fixed
- **The timeline showed subagents as main threads, and (in SDK mode) demoted real main
  threads to subagents.** Reported from real use twelve days earlier, but unfixable until
  now: no capture on hand contained a single `Task`/`Agent` spawn (194 records across three
  days — zero spawns), so there was nothing to derive a rule from, and changing the
  classifier without data would have been guessing. A dedicated capture settled it —
  `claude -p` spawning `Explore` / `general-purpose` / `Plan` serially, 15 records, ground
  truth written down by hand — and it showed that **CC states subagent identity on the wire
  itself**, in the billing header of system block[0]:

  ```
  main:     x-anthropic-billing-header: cc_version=2.1.220.8f8; cc_entrypoint=sdk-cli;
  subagent: x-anthropic-billing-header: cc_version=2.1.220.a83; cc_entrypoint=sdk-cli; cc_is_subagent=true;
  ```

  Present on 8/8 subagent requests, absent on 7/7 non-subagent ones. No heuristic needed —
  and the same data refuted every previously assumed signal:

  | Assumption | Measured |
  |---|---|
  | Subagents start their own `X-Claude-Code-Session-Id` → usable as a discriminator | They **reuse the parent's** (13 requests, one id) → session id is a *lane* key only |
  | `cc_entrypoint` changes for subagents | 15/15 `sdk-cli` — subagents **inherit** it |
  | CC withholds the Agent tool from subagents (no nesting) → "no Agent tool ≈ subagent" | `general-purpose` subagents **do** carry it (75 tools) |
  | `system` block[1] wording distinguishes them | 15/15 identical (`"You are a Claude agent…"`) |

  Tool count is no signal either: one main thread went 40 → 77 tools within a session
  (deferred tool loading), overlapping the subagents' 62/75/71.

  Four fixes, all evidence-driven:

  1. **`cc_is_subagent` is now the authoritative check**, evaluated before any main-thread
     fingerprint (subagents carry main-thread wording, so wording-based ordering must lose).
  2. **The main-thread fingerprint list gained `"you are an interactive agent"`** and the
     unknown-shape fallback flipped from `subagent` to `main`. `MAIN_SYSTEM_FP =
     "you are claude code"` only ever matched interactive mode; in SDK mode nothing matched,
     so every `claude -p` main request fell through to `tools_n > 0 → subagent` and was
     demoted — 5/5 of them, and the entire error set behind the old 10/15 accuracy.
  3. **`build_dag` no longer skips records already classified `main`.** That one-line
     short-circuit locked out the strongest signal available: once a subagent was misread as
     main it could never be corrected ("main for life"), and each misread subagent then
     became its own "main" lane — exactly the wall of main threads that was reported.
  4. **Spawn-prompt alignment switched from prefix match to substring match after stripping
     `<system-reminder>` blocks.** Subagent first-user messages are injected with the same
     reminder preamble as main threads, pushing the spawn prompt past the start, so
     `startswith` in either direction matched **0 of 8**. Stripping the reminders leaves the
     spawn prompt verbatim at the front: 8/8. (Injection size also varies by agent type —
     `Explore`/`Plan` get ~550 characters, `general-purpose` gets the full CLAUDE.md at
     ~9,960 — so a fixed-length prefix could never have worked.)

  Accuracy against hand-recorded ground truth: **10/15 → 15/15**. On the capture day the
  timeline goes from 0 main / 13 subagent lanes-worth of confusion and **zero** spawn edges
  to 5 main / 8 subagent with **3** spawn edges, one per actual spawn.

- **One CC session was split across many "main" lanes.** The lane key was an md5 of
  "first user text + user_id", which its own docstring admitted broke on autocompact. It
  breaks more widely than that: on the 866 MB reference day that hash yields **42 distinct
  grouping keys for 13 real sessions**, and on an earlier day it split 2 sessions into 7+2.
  The lane key is now the CC session id (`X-Claude-Code-Session-Id`, falling back to the
  session id inside `metadata.user_id`, then to the old text hash for captures that have
  neither) — measured coverage 15/15 and 2993/2993. Subagents, which share the parent's
  session id, are keyed per spawn instance instead (spawner id + spawn prompt), so all
  requests of one subagent land in one lane; previously the lane key was built from the
  record's own id, giving each request of the same subagent its own column.

- **Self-tests grabbed a fixed port and, when it was taken, silently tested someone else's
  instance.** `proxy_selftest` bound its app to 5051; with a `serve` daemon or dev server already
  there, Flask's bind failed inside a background thread while the main flow printed "started" anyway
  and sent its requests to **that other instance** — whose upstream is a real endpoint, so the fake
  token came back 401 and the failure pointed at "forwarding is broken", which was not the problem at
  all. It also wrote two fake requests into the other instance's captures. Self-tests now pick free
  ports from 5150 (outside the tool's own 5051–5100 range), the mock upstream port is threaded through
  the fake settings instead of hardcoded, and "the app is up" is a `/api/proxy/status` liveness
  assertion rather than a `sleep` followed by an unconditional announcement. Verified by running the
  suite green *while* a dev server held 5051, with that instance's capture count unchanged.

- **Stale capture indexes were silently reused after the index schema changed.**
  `_read_idx_entries` validated only `off`/`len`, so adding fields to an index record left
  old indexes structurally "valid" — the new fields would read as missing on older captures,
  the classifier would quietly fall back, and nothing anywhere would error. Index records
  now carry a schema version; a mismatch discards and rebuilds the whole index (the file is
  deleted first, otherwise the append-mode backfill would re-append behind the stale rows
  and re-trigger a rebuild on every read). Measured rebuild: 5.3 s for a 426 MB day, then
  0.001 s from cache.

### Changed
- **The config check now declares its own scope.** `check()` returns `scope: "settings_file"` plus a
  note, and the UI drawer says it outright: the check reads the settings file, while a **running** CC
  session keeps the environment it was started with. Right after a user edits `settings.json` the
  check can report zero issues while the session they are talking to still behaves the old way —
  observed live, when removing an effort setting turned the check green while the running session
  stayed on `max`. Reading another process's environment to close that gap was deliberately rejected:
  cross-platform, permission-sensitive, and this tool is often not CC's child process at all (it
  isn't when launched by double-click). A rule that cannot tell the difference does not get added —
  it says what it covers instead. (`/api/diagnose/errors` has no such blind spot: it looks at requests
  that actually happened.)
- **Timeline lane labels show the real CC session id** (first 8 characters, full id on
  hover) instead of the internal lane hash — it matches the `.jsonl` filenames under
  `~/.claude/projects/`, so a lane can be traced to its session. Subagent lanes keep their
  spawn-instance code, since they share the parent's session id and would otherwise display
  a label identical to their parent's.
- **`dev_seed.py` sample captures now have the shape of real traffic**: 3-block system
  (billing header / identity / body), `X-Claude-Code-Session-Id` request header,
  `metadata.user_id` as a JSON string, and for subagents a `cc_is_subagent=true` billing
  header plus a `<system-reminder>`-wrapped first user message. The old samples used shapes
  that do not occur in reality (no billing header, no session header, bare spawn prompt), so
  none of the identity or session logic was exercised by UI self-tests — the same class of
  blind spot that shipped four bugs in v0.2.0. A second subagent request was added to cover
  "multiple requests of one spawn share one lane".
- `tools/lane_probe.py` reports the authoritative flag and cross-checks it against the
  classifier's verdict, flagging disagreement in either direction — it is now a regression
  probe for new CC versions rather than a rule-discovery tool.

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
