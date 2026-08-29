# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md).

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed to use it from an agent.
- **Current status**: **v0.4.19 (2026-08-29)** is the release where the trajectory's eight views stopped being a separate piece of software: they now carry the same three appearances, the same packaged fonts and the same type scale as the rest of the app, and embed without a second header or a second scrollbar (the child posts its height, the parent posts the visible viewport back, and switching appearance re-renders in place rather than reloading a page whose payload took ~20s to compute). The first contrast audit of that page found 14 AA failures, all in the two light appearances, all one shape — `--agent` used as a text colour — and fixing that shape took it to 0 across eight views x three appearances. The same release corrects nine things the first cut got factually wrong, including 129.9 hours of auxiliary model time in a 44-minute session, an "undefined seconds" footer, a hard-coded tool count from the prototype's own recording, and a "-1 retries" line. The eight views themselves landed here too. Previously, **v0.4.18 (2026-08-28)** closed the gap that made step briefs unreadable — the summariser now receives what you asked for, what each action acted on, and what it returned (previously 0 of 6.8 MB of tool output reached it). Briefs are three-part with a checkable `got`; turn headings separate the overall goal from what the turn is solving, and "wrote it, never verified it" is computed rather than asked. Verified end to end on a real 199-step recording. Previously, **v0.4.17 released (2026-08-27)** — one round of real-use feedback carried end to end, mostly about turning AI analysis from a gamble into a pipeline you can resume: the pipeline was inverted (step briefs first; the turn level and the subagent verdicts both roll up from them), batches run concurrently (the same 126-step recording went from the 26-minute range to 196 seconds), each phase is persisted as it completes and re-running fills only the gaps (20 missing steps cost 4 batches and 64 seconds), and every subagent lane now carries one line each of task / problems / resolution / outcome. Three real bugs went with it: after an auto-update restart the new process **reused the old extraction directory** (new version number, old UI — `run.log` has the whole scene), the reasoning drawer sized itself for "once stuck" and pushed long translations entirely off-screen, and rebuilding the index filed every analysis sidecar as a ghost sticker. Two capabilities were added: a drawer that sizes itself to the viewport and can be dragged (4K, laptop and ultrawide each get something sensible), and **portable snapshot bundles** — a snapshot plus its AI analysis packed into one file and carried to another machine without paying for the analysis again. Two more landed with the same release: the API browser's **parameterised endpoints became usable** — ten rows that only said "needs a path arg" (plus one Render link that could only fail) now carry an editable URL pre-filled with this machine's own rid and sid — and that page finally carries **all three appearances** instead of folding them into two, a fold that had been serving Lab Daylight the Classic Warm palette; its first colour audit found three more AA failures on the way. The previous release, **v0.4.16** (2026-08-27), is about the analysis view growing from a skeleton into something you can read, and about the gates that let three bugs of one shape through. A recording's **subagents are now part of the story**: `Task` farmed work out into other requests, so the main line only ever kept the tool call and the final report; the view now walks the recording back, nests each lane under the step that spawned it, and drills into any subagent step's raw reasoning (measured: 6 lanes, 6 of 6 pinned to a step, 158 subagent steps recovered). Step briefs became **two-tier** — a one-line title over the detail carrying why / what turned up / what was abandoned — and the raw reasoning moved from the bottom of the page to a **sticky panel on the right**. Archives now say **which machine and which version produced them**. And a full-surface colour audit took **25 AA failures to zero** (15 of them in Classic Warm alone), leaving behind the rule that a colour token can only serve one light/dark relationship. Three "reference to a name that does not exist" bugs — an undefined variable, an undefined CSS token, an undefined i18n key — got two new gates and one measured, deliberate refusal. Before that, **v0.4.15** (2026-08-25), layered recording storage: compaction in place (500 MB → 14.8 MB, 33.9x, byte-for-byte reversible), portable `.ccwa` archives, and import into a `sources/<label>/` namespace. **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. **Close the self-improvement loop.** `/api/diagnose/trends` now answers "new or recurring?" reliably, but turning a recurring pattern into a check is still manual — `effort_max_rejected_upstream` exists because a human noticed a recurring failure and wrote a rule for it. Automating that half is what makes the radar and the trends more than a reading exercise.
  2. **Decide whether turn origin should ever be corrected at runtime.** Development-time ground truth now exists: a probe joins recordings against Claude Code's local conversation logs and measures the heuristic (99.8% agreement, zero human turns demoted — see §2.6 of `docs/reference/开发约定.md`). What is deliberately *not* decided is whether the shipped app should read those logs to correct itself live. It currently does not, and that restraint is the point: the app's data surface is the traffic it recorded and one settings field, so widening it is a trust decision, not a precision tweak. Related and still open: the same measurement showed retry storms inflate turn counts (one day: 2,049 "turns", 2,000 of them 504 retries of three real questions) — whether the classifier should merge retries, or keep showing them honestly, needs its own argument.
  3. The recording-blind-spot audit (protocol side and capability side) closed across v0.4.3–v0.4.6; method in `docs/reference/开发约定.md` §2.5 and unit 0 of `docs/methodology/同类工具构建手册.md`.
  4. **Storage follow-ups now that compaction exists.** Two are measured and deliberately deferred: the skeleton's pointer lists are a prefix-extension of the previous request's in the same lane, so delta-encoding them should roughly halve a pack again (estimated 477 MB → ~10 MB); and retention still only deletes — it could compact first and delete much later, which changes what "keep 30 days" costs. Neither is needed for the current ratio to be useful, which is why neither shipped with it.

## Unreleased

- **The eight views stopped looking like a different piece of software.** They shipped as the
  prototype had them: a private near-black teal palette, their own font stack, 8.5px labels, their
  own sticky header and their own scrollbar. Embedded in an app whose default appearance here is
  Classic Warm, that reads as a slab of black pasted onto cream paper — with the nav wrapping onto
  two lines and two scrollbars fighting each other. Four things had to change together, because any
  one of them alone still leaves a page-inside-a-page: the palette is now **the same semantic tokens
  in three appearances** (the page keeps its own token names, the values come from the main
  interface's; the appearance arrives as `?theme=` and falls back to the `ccwa_ui_theme` cookie when
  the page is opened on its own); the **packaged fonts** are declared in the page itself
  (`/static/fonts/*` is same-origin — without this it silently fell back to system YaHei/Consolas,
  which is exactly what "two typefaces side by side" looks like); the **height is negotiated with the
  parent** (the child posts its `scrollHeight`, the parent sizes the iframe, so the whole page has
  one scrollbar) and the parent posts the **visible viewport** back, which is what lets the drill
  drawer float over what you are actually looking at instead of being pinned to the top of a
  several-thousand-pixel document; and switching appearance **re-renders in place** rather than
  reloading — the payload is embedded in that HTML, so a reload would make the server recompute the
  whole thing. Type scale went up with it (8.5px labels are gone; nothing below 10px remains).
  Measured: the first contrast audit of that page found **14 AA failures, all in the two light
  appearances, all one shape** — `--agent` was being used as a text colour when it is a colour for
  borders and fills. Fixing that shape took it to **0 across eight views × three appearances**.

- **Nine things the first version got factually wrong.** A 44-minute session reported **129.9 hours**
  of auxiliary model time (a missing division by 1000); the footer said the phase split took
  "**undefined** seconds" (the field it read has never existed); the autocompact footnote carried a
  hard-coded **190** — the tool-call count of the prototype's own recording, a lie on any other one,
  now computed as "the longest single request only has N of the union's M"; the counterfactual said
  "0 blocks, the first gave a full reason (…), the other **-1** were retries of the same kind";
  the same quantity appeared as 20 minutes on a card and 21 in a footnote, and as 20 in one view and
  21 in another, because each site rounded on its own; a valve banner asserted a compact that had not
  happened on that recording, and explained itself in terms of "the seventh generation" — prototype
  jargon that means nothing to a user; an empty counterfactual told the reader to "run optimal.py";
  the payload said it was generated by `build_factors.py` rather than by a version of this program;
  and every one of the eight state-snapshot cells was a single ellipsised line, so failure text and
  what the user actually said were unreadable. Legends were missing where two colours needed telling
  apart, empty lanes said nothing rather than "there were none of these", and long material names
  still collided with their L0 badge because truncation counted characters rather than measuring
  pixels. All fixed and verified against two real recordings (34 and 138 nodes) with the numbers
  read back out of the DOM.

- **A recording that cannot be drawn now says so in the same skin.** The error path went through
  `jsonify`, and `?format=html` handed that to the API browser — so a recording whose day had been
  archived rendered a full "API response" page inside the analysis view, and the front end scraped
  its `innerText` for an error message, producing "Expand all / Copy / Raw JSON". It now returns a
  small themed page instead. The smoke probe learned three assertions about this slot (the height
  bridge really fired, the appearance really followed, and an honest error page counts as rendered —
  but only after trying up to three recordings, because only ever hitting the archived case means
  never testing the views at all).

- **The availability banner stopped contradicting itself.** "31 steps · 26 of them with reasoning ·
  **0 chars**" is not a sentence: the blocks are there, the upstream (GLM via the gateway) returns
  signatures without plaintext. Those two cases now read differently.

- **The analysis view's tree slot became the trajectory's eight views.** One recording can now be read
  eight ways — state-snapshot sequence, material lineage, verification matrix, valves & loops, cost &
  variance, counterfactual table, material lifeline, optimal timeline — replacing the old mechanical
  "decision-tree" slot (the list view stays). The foundation is the **union of all main-line requests'
  blocks** (deduplicated by tool_use id / tool_result id / text md5), not the single longest request:
  autocompact trims the first half of the history, and only the union recovers it (measured on the
  prototype: 190 → 377 tool_uses, start moved 69 minutes earlier). The layering is constitutional:
  facts are computed (nodes, materials, lineage, verification levels, valves, debt, the necessary
  closure BFS that produces the counterfactual), semantics are model-written (phase split from
  program-generated candidate boundaries, state-snapshot quadrants, one-line node briefs), and the
  program overwrites the factual quadrants at compute time — the model cannot touch facts. The
  semantic layer runs as a resumable POST pipeline (split → snapshots → briefs, progress via the
  existing analysis-progress channel) and is cached per snapshot (`<sid>.semantic.json`, now also
  carried inside portable snapshot bundles). Recordings whose day was archived to `.ccwa` say so
  honestly instead of rendering half a run. Verified on two real recordings end to end (34 and 138
  nodes; 34/34 and 138/138 brief coverage, zero failed batches). One round of vision-model review
  (8 view screenshots, P0×0 / P1×8) was verified item by item and fixed: the three conflicting
  "model time" numbers turned out to be three true values at different calibers (all requests vs
  node-only) — the cost card now splits them explicitly; GLM upstreams return signature-only
  thinking blocks (44 blocks, 0 chars of plaintext), and the drill-down now says so instead of
  "0 chars"; empty states, phase-label overlap on short phases, and a footer that asserted an
  autocompact that never happened were all fixed.

## v0.4.18 - 2026-08-28

- **The summariser never saw what you asked for, and never saw what any action returned.** Reading a long
  session back, the step briefs could not answer the one question they exist for — what did the AI actually
  do. That was not a wording problem. Three fields were missing from the model's input entirely. `trigger`
  was passed as a bare kind (`"user"` / `"tool_result"`), so **not one character of your instruction reached
  the model**; tools were passed as names only, with no target and no result. Measured on three real
  recordings from one day: 572 tool calls produced 572 results totalling **6.8 MB**, of which **0 bytes**
  ever reached the summariser, and 11%–37% of steps (the pure-execution ones — precisely the steps that
  change reality) were dropped from the input wholesale. A model that can see the motive but neither the
  object nor the outcome of an action has one move left: paraphrase the thinking. That is why the old
  `detail` ran long and said little. Now every tool call carries a **program-extracted result digest**
  (≤90 chars, type-aware: images are counted, never inlined — one PNG read came back as 33,768 characters
  of base64), a normalised **verb** (read / search / write / exec / fetch / delegate) and a **target**
  (the file, script or command it acted on). Pure-execution steps are no longer thrown away: their actions
  and results are folded into the preceding step that made the decision, so the model reads the whole
  consequence of a decision **without costing one extra call**. The instruction cap rose from 200
  characters to a head-and-tail budget of 2,000 — on one multi-agent session, 26 of 46 turns had been
  hitting that 200-character wall, and a teammate report is 1,838 characters.

- **Step briefs are now three parts, and shorter for it.** `title` (≤20 chars, what it did) / `why`
  (one line, only when the thinking really weighed something) / `got` (one line, the result — which
  simply could not be written before, because the result was not in the input). `got` is encouraged to
  quote a short fragment of the actual output (`CE=0`, `Traceback`, `572 devices`), which makes it both
  shorter than a paraphrase and **checkable**: the quoted fragment has to exist verbatim in that step's
  recorded `tool_result`. Concision comes from the schema, not from telling the model to be brief.
  All three generations of the format (single `brief`, two-part, three-part) still render — a published
  `steps_prompt` contract must not be invalidated by a schema change.

- **Turn headings now separate the overall goal from what this turn is solving.** Reading a list of turns,
  you could not tell whether the run was drifting, because every heading answered the same question.
  A turn now answers five: `said` (what you asked — **compressed into one line, not quoted verbatim**),
  `solving` (which part of the whole task this turn eliminates), `done_when` (only when you actually
  stated a completion condition — the model is forbidden to invent one), `outcome` (what came of it) and
  `risk`. Above them sits a session-level `goal` and `drift`, produced by the one call that ever sees the
  whole run. Two of the inputs are **computed, not asked**: which materials a turn touched, and whether
  what it wrote was ever read back or run again — "changed five files, verified none" is a fact, not a
  judgement, so the program answers it.

- Verified end to end on a real 199-step / 30-turn recording: 124 briefs in 17 batches, 0 failures, and
  turn coverage 199/199 steps. Command-line target parsing was hardened against four shapes found in
  real traffic that all used to collapse into one useless material name (`cd "…" && uv run python x.py`,
  `uv run python x.py`, `python -c`, and a quoted absolute path to an executable).

## Earlier versions

v0.4.16 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
