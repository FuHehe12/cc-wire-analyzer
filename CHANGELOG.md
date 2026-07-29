# Changelog

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Detailed change history in the sections below. Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection.
- **Current status**: **v0.4.0 released** (2026-07-28). Three additions landed together: **lane identity finalized** (the billing-header flag `cc_is_subagent=true` is the authoritative signal, accuracy 10/15 → 15/15), **config doctor** (`doctor.py`, 8 read-only rules), and **failure grouping** (`diagnose.py`, measured 2719 failures → 7 groups), plus a UI readability pass (i18n for `stop_reason`/`err_kind`, response-headers panel open by default with wire-only fields bolded) and a fix for parallel same-template subagent lanes collapsing into one. All six self-tests green; verified against real captures (the 866 MB day) and a repackaged-exe smoke test before tagging.
- **Next steps**:
  1. **Diagnosis loop**: ① a UI entry for failure grouping (currently API/CLI only); ② recurring failure patterns hardened into doctor rules (`effort_max_rejected_upstream` originated this way — the bar: reproducible? statically decidable? false-positive risk?); ③ cross-day trends (furthest out, deferred).
  2. **Identity residual** (deferred): interactive-mode (`cc_entrypoint=cli`) subagents are **not yet measured** (the v0.4.0 round was all `sdk-cli`). The two-layer rule means a missing flag can no longer cause a main thread to be misread as a subagent, but fully closing the loop needs a capture of an interactive session spawning subagents.

## v0.4.1 - unreleased

> In progress. This entry records the user-driven UI/doc batch from 260729; other v0.4.1 doc work
> (README / AI_USAGE / API契约 / app.py) is still uncommitted in the working tree and will be folded in
> before the version is tagged.

### Added
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
