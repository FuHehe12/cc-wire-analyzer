# Changelog — released versions

> Full notes for every released version, v0.4.21 and earlier. The current version and the
> unreleased rolling list live in [CHANGELOG.md](CHANGELOG.md), which is also what CI reads
> to build a release's notes. Each version below is also published, unchanged, on its
> [GitHub Release page](https://github.com/FuHehe12/cc-wire-analyzer/releases).
>
> Why the split: CHANGELOG.md serves two readers at once — the overview at its top is read
> on every handoff and needs to be short, while the history below it needs to be complete.
> Those two pull in opposite directions, so the history moved here.


## v0.4.21 - 2026-08-31

### Improved

- Today's recording is compacted as it goes: the finished prefix is sealed into segments once it
  crosses a threshold and merged back into one pack the next day. Off by default; the settings page
  has the switch and the threshold (20–2000 MB, default 200). Measured 701 KB → 36.8 KB (19.1x),
  byte-identical on unpack.
- The agent-facing brief now exposes the analysis the app has already computed: its endpoint list
  went from 3 to 8 and names the fields `trajectory` holds. A second task (`?task=flow`) asks for a
  diagram of how the run actually went.

### Fixed

- Archiving a day that had been rolled kept only its last segment.
- The agent-facing brief was half-translated: `lang=en` returned an English task wrapped in Chinese
  labels.

## v0.4.20 - 2026-08-29

- **The one "AI Summary" button became two, one per slot.** It used to branch on which slot you were
  looking at: the same label ran `/analysis` in the List slot and `/trajectory` in the 8-views slot —
  two different jobs at two different prices behind one word. There are now two buttons, both always
  present, each showing its own state ("Summarise list" / "Re-run list" / "Fill N steps" vs
  "Summarise 8 views" / "Re-run 8 views"), so you can see whether the *other* slot has been
  summarised without switching to it. Only one may run at a time — both pipelines call the same model
  endpoint, and running them together only multiplies the failure and rate-limit surface. "Recompute
  from scratch" now names its target too, and stays list-only: the customisable summariser prompts
  apply to that pipeline, the trajectory's task descriptions are built in.

- **Clicking the eight-view slot now changes the screen in the same frame.** Making the iframe
  transparent with a content-driven height had an unintended consequence: until the child document
  loads, nothing moves at all — and a 138-node recording takes 5.3 seconds and 1.2 MB to produce, so
  the only feedback was "I clicked and nothing happened". A skeleton card now renders with the click
  (measured at 53ms) and says why a long recording takes a few seconds.
- **The same recording is no longer recomputed every time you open it.** `trajectory.compute` ran on
  every request for a snapshot that cannot change; a two-entry in-process cache of the rendered HTML,
  keyed by snapshot plus semantic-layer fingerprint and dropped when the semantic pipeline writes,
  takes the 138-node recording from **5.18s to 0.03s** on reopen.

## v0.4.19 - 2026-08-29

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

## v0.4.17 - 2026-08-27

- **After an auto-update restart, the version number was new and the app was not.** The user pressed "Install and restart", Settings duly showed the new version, and the app still behaved like the old one — closing the window and reopening it fixed it. `run.log` had the whole scene: the new process announced `version=0.4.15`, and one second later `GET /static/fonts/Inter.ttf` returned 404 and `marked.min.js` returned 500, both pointing into `Temp\_MEI76282` — **the previous process's extraction directory**. The cause is that `Popen` inherits the whole environment, and a frozen build's environment carries the PyInstaller onefile bootloader's private variables (`_PYI_PARENT_PROCESS_LEVEL` / `_PYI_APPLICATION_HOME_DIR` / `_PYI_ARCHIVE_FILE`). The new executable's bootloader reads them, concludes "I am the already-extracted child process", **skips extraction and reuses the old directory — which the dying process is busy deleting**. Hence the precise mismatch: Python code came from the **new exe** (so the version was new) while templates, static assets and fonts came from the **old directory** (so the UI was old and half its assets 404'd). The symptom also drifts, because it races the old bootloader's cleanup — whatever it had deleted is what goes missing — so "try it again" can never tell you whether it is fixed. The relaunch now strips `_PYI_*` and `_MEIPASS2` from the child's environment and passes everything else through untouched (PATH, TEMP and proxy settings are still needed), with a self-test that fails if any of them leak. One related thing was measured and **deliberately left alone**: after a restart the port drifts from 5051 to 5052, because the old process's SSE connections sit in TIME_WAIT and the free-port probe's bare `bind` is stricter than the criterion werkzeug itself uses. All three fixes are worse than the problem — `SO_REUSEADDR` would break "find a free port" outright (on Windows it permits binding to a *live* listener), waiting out TIME_WAIT costs 120 seconds, and the actual harm is zero because `port.txt` is updated. It is written down so the next person who sees 5052 does not investigate it again.

- **The analysis pipeline was inverted: step briefs come first, and both the turn level and the subagent verdicts roll up from them.** Three pieces of feedback pointed at one chain, and fixing them separately would have undone each other. (1) **It was serial** — the batches have no dependencies between them and were still waited on one at a time: a 126-step session is 26 batches and took tens of minutes. They now run concurrently (4 by default, 1–8 in Settings; the ceiling is not about throughput but about not driving the upstream into rate limiting), taking the same recording **from the 26-minute range down to 196 seconds**. (2) **Long recordings were summarised only in part, and re-running produced the same gap** — because the turn level was fed the L0 skeleton, which has a 20k-character budget and cuts from the middle when it overflows: of the 126 steps in that 420k-character recording, **only 62 ever reached the turn-level model**; the 282-step one lost 142. That is deterministic, which is exactly why "re-analyse" changed nothing. The deeper problem was that **the skeleton contains no reasoning text at all** (only step numbers, tool names, character counts and mechanical signals) — so "what is this turn doing" was always inferred from tool names, while the layer that actually read the reasoning was the step brief. The turn level now takes step briefs as its input, batched by turn and **never splitting one turn across two batches**; measured coverage is **126 of 126 steps**. The skeleton's own fallback truncation changed from "halve it" to "trim until it fits" (it used to cut down to 16,799 characters against a 20,000 budget, throwing away a dozen steps for nothing). (3) **Subagents had only a step-by-step flow** — six lanes expanded is 158 rows, and none of it answers "did it succeed?". Each lane now costs one extra small call and produces four sentences — **task / problems hit / how it was resolved / outcome** — sitting at the top of that lane when you expand it.

- **A failed analysis can be picked up where it stopped instead of paid for twice.** Failures used to be a single number ("2 batches failed") — which told you neither which steps were lost nor how to get them back — and "re-analyse" re-ran everything, discarding tens of minutes of completed work. Three things changed together: failures are **recorded as specific step numbers**; each phase is persisted as it completes (previously nothing was written until the whole run finished, so any exception anywhere threw the entire run away); and "re-analyse" now fills gaps by default, with a separate "Recompute all" button — the two differ by an order of magnitude in cost, and hiding that behind one button is an accident waiting to happen. Measured: delete 20 steps, press fill, and it runs **4 batches in 64 seconds** rather than 26 batches. Retries also became backoff rather than "immediately once more" (an immediate retry usually lands on the same rate limit), while configuration errors give up at once — if the key is missing, it will still be missing on the third try. Concurrency also changed the progress text: with several threads in flight, "batch N" is wrong whichever one you report, so it now counts completions against a total, per phase (main line / subagents / turns / subagent verdicts).

- **After translating, long output was "cut off with no scrollbar".** The drawer is declared `overflow:auto`, so on paper it should always produce a scrollbar — which is why this one was reproduced before it was changed. The cause is that **its height is computed for "once stuck" while it was not yet stuck**: `top:82px` only applies after the page has scrolled to the sticky threshold, and on open the drawer sits at its natural position (measured: y=770) while its height is a fixed `100vh - 104px` = 1138px. 770 + 1138 overshoots the 1242px viewport, leaving **666px off-screen** — and the translation renders *after* the reasoning text, landing entirely in that off-screen stretch, along with the drawer's own scrollbar. A second cause stacked on top: the reasoning `pre` carries its own 420px scroll box, which fills the small visible strip, so the wheel scrolls the inner element and the outer drawer never moves. The height is now computed from **where it actually is** (the smaller of "available height once stuck" and "from here to the bottom of the viewport", rebound on scroll and resize), the drawer is allowed **exactly one scroll container**, and opening it scrolls the page to where it sticks. This also settles a latent bug: UI scaling uses `zoom` on the root element, under which `vh` resolves to more than the real viewport — the new calculation does not use `vh` at all.

- **The reasoning drawer is no longer pinned to 410px.** The user works across three machines with different aspect ratios (4K, laptop, ultrawide) and got the same narrow strip on all of them, while the entire point of that panel is to spread the source text out and read it. The width now derives from the viewport (`clamp(320px, 30vw, 760px)` — measured 432px at 1440, 760px at 2560), the divider can be dragged, and the chosen width goes to **localStorage rather than config**: this is a "comfortable on this screen" preference, and syncing it to the other two machines would be wrong. The narrow breakpoint still drops the drawer below the narrative, with no grip in that mode.

- **Stickers can now be carried to another machine the way recordings can.** Recordings had `.ccwa` archives; snapshots had nothing — and the expensive thing about a snapshot is not the snapshot, it is the `analysis.json` beside it: a 97KB analysis measured 27 batches and 26 minutes. Not being able to move it means another machine (or another person) must pay for it again. Selecting stickers and pressing "Export bundle" now packs the snapshot, its AI analysis and its chat history into one file. It **reuses the `.ccwa` extension and distinguishes by `kind` in the manifest**, so there is still only one "Import" for the user and the tool works out what it was handed. Signing matches archives: `host` takes the machine name and never the user name, `tool_version` takes the real version. **Colliding ids are never overwritten** — a clash lands under a new id, the UI says so plainly ("N clashed with local ids and landed under new ones — nothing local was overwritten"), and the envelope records which machine it came from. Measured round trip: 126 step briefs, 8 turn headings and one subagent verdict opened intact on "the other machine" without a single further API call.

- **Fixed: rebuilding the index filed every analysis sidecar as a snapshot of its own.** The `snap_*.json` glob also matched `snap_x.analysis.json`, so every analysed snapshot grew a ghost sticker with no kind and no label. The criterion is now the sid pattern itself rather than "exclude .analysis", so adding another sidecar suffix later does not send anyone back here.

- **Fixed: sticker tags measured 4.21:1 in Classic Warm.** The previous release's full-surface audit that took 25 AA failures to zero missed this one because **no sticker on screen had a tag at the time** — the probe only sees what is currently rendered. That lesson matters more than the colour value: an audit is only as good as what is on screen while it runs, so this pass was done against real data, with tagged stickers, expanded subagent cards and the drawer open.


- **The endpoints that need arguments can finally be opened from the API browser — and the examples are this machine's real data.** `/view` lays out every endpoint the AI side can reach, but the ten most valuable rows were dead: anything with `<rid>` / `<sid>` in the route said "needs a path arg" and stopped there — and what an agent reads most is exactly `/api/captures/<rid>` and `/api/snapshots/<sid>/*`. The page fell silent precisely where it had the most to say. The tenth was worse: `/api/snapshots/diff` has no `<>` in its route, so it carried a live "Render" link, while what it actually wants is `?a=&b=` — two sids. **Clicking it could only fail.** A dead row is at least honest; a button that cannot work is actively walking someone into a failure. Each row now carries an editable, complete URL, pre-filled from **real local data**: the first rid of the most recent day that has any, and for snapshots the **one that has already been summarised** (an `/analysis` pointed at some other snapshot opens empty, and an empty page reads as "this endpoint is broken"). A placeholder only answers "what is the shape"; it cannot answer "what do I have on this machine" — and the latter is this tool's entire claim. Only when there is genuinely nothing does it fall back to a reference form, and then it **says so on the row** — not saying so would be inviting someone to copy an address that cannot work. Examples carry every argument they need (`date=` for captures, both `a`/`b` for diff): the whole value of an example is that copying it works, and one missing argument turns it back into a placeholder. The self-test **actually runs** every example and asserts HTTP 200 — whether an example is alive or dead has to be decided by a machine, not by looking at it once.
- **The browser page went from two appearances to three, and one case of mistaken identity is fixed.** The main UI has Classic Warm / Dark Professional / Lab Daylight; this page folded them into light and dark, and the fold had a real error in it: **choosing the teal Lab Daylight and clicking through gave you warm gold** — it was serving the Classic Warm palette. Not "one missing", but the wrong one. An appearance is not decoration; it is the signal that you are still inside the same piece of software — and this page in particular exists to be checked against. A shift in hue reads as "did I click into something else?". All three now get their own tokens, copied value by value from the matching tokens in `index.html` (no separately tuned near-colours — two places tuned separately is the next divergence), and the header gained a three-swatch switch that writes the **same** cookie and localStorage key, so it is not a second source of truth but a second door to the same setting (`/view` can be opened by typing the URL, and until now whoever arrived that way got dark and could not change it). That came with this page's **first colour audit ever**, which measured three real problems: dark `--faint` sits at 3.58:1 on the card — and that is the colour `.ep-why` / `.hint` / `.empty` use; in both light themes `--accent` as link text is 2.94:1 (`--accent` is for borders and solid fills; text needs its own `--link`, a lesson `index.html` had already learned once); and dark `--null` fell just short at 4.45:1. Index, response and guide pages across all three appearances: zero AA failures.

## v0.4.16 - 2026-08-27

- **A recording's subagents are now part of the story it tells.** Reading what an agent did has always been missing its second half: a snapshot holds one request — the main line's full history — and everything `Task` farmed out lives in *other* requests, so the main line keeps only the tool call and the final report. What the subagent actually read, weighed and abandoned was in the recording all along, one join away, and the analysis view never made it. It does now: `GET /api/snapshots/<id>/subagents` walks the recording back, returns each lane's own skeleton, and says which main-line **step** spawned it; the list view nests each lane under that step as a collapsed card (six lanes expanded at once is 158 rows — that buries the narrative this view exists to tell), and one click opens it as its own brief flow, with `?lane=&step=` giving any subagent step's raw reasoning. Nesting goes three deep, because subagents spawn subagents. **Nothing here is a new heuristic**: lanes come from `X-Claude-Code-Agent-Id`, parentage from the same `trigger` edge the DAG has used for a year (spawn prompt's first 300 chars ⊂ the subagent's first user message), and pinning to a step is that same rule aimed at one step's `Task` prompt. Measured on a real 137-step run: 6 lanes, 6 of 6 pinned to a step (#18, #31, #54×3, #97), 158 subagent steps recovered. What cannot be answered says so — a lane whose spawn prompt does not match is listed separately with the reason, and if the day's recording was cleared or archived away the pane says *that*, because rendering "no subagents" would be inventing a fact. The same run also generates briefs for those steps, in the same click, so opening a lane costs nothing extra later — and because that click now costs three times what it did (measured on this run: 27 batches, 26 minutes, main line plus six lanes), the button stops saying "analysing…" and starts saying *how far it has got*: `main line 3/9`, `subagent 2/6 · 4/7`. A progress bar frozen at "12/27" would read as more alive than no progress bar at all, so it is cleared whether the run succeeds or fails.
- **Step briefs are two-part now, and the raw reasoning opens beside them instead of at the bottom of the page.** The previous version dropped the length cap and asked for why / what turned up / what was abandoned — the information was right, but it came back as one long paragraph, and the row rendered it as one flex element: a hundred steps of undifferentiated text. The task now asks for a `title` (one line, verb-first, ≤24 chars) plus a `detail` that carries the judgment, and the row renders them as two tiers — scan the titles, read the detail where it matters. The old single-`brief` shape still renders (cached analyses and any custom prompt in Settings keep working; it lands in `detail`, and the row falls back to its mechanical lead rather than passing a paragraph off as a headline). Clicking a step used to render its reasoning **after** the entire steps card: on a 137-step recording you scrolled past several screens to read it and scrolled back to find your place. It is now a sticky panel on the right, clearing the header, closing on Esc or a second click on the same row, and never re-rendering the list underneath — the whole point is to stop making you翻. Tree view drills into the same panel.
- **The API browse page finally has a door.** `/view` shipped in v0.4.15 to tear down the wall between the two halves of this tool — humans read the GUI, agents read the HTTP API, and after you hand an agent that one line, *what it actually reads has been invisible to you*. The page did that job; nothing in the interface linked to it, so the only way to find it was to read the changelog. A user went looking in Settings and could not find it. The "For your AI" card now lists it right under the manual endpoint, clickable and copyable, noting that `?format=html` on any endpoint does the same. Its address comes from `location.origin` like the manual's — hardcoding 5051 is a hole this project has fallen into before.
- **Fixed: two rows in Settings were printing i18n key names at the user.** `set.anaTurns` and `set.anaSteps` appeared verbatim on the analysis-prompt rows: the HTML referenced four keys that were never added to any of the three tables, and `t18()` falls back to returning the key. `check_i18n_js` was green throughout, because it asks whether the three tables agree with each other — and a key missing from all three leaves them in perfect agreement. That is the third time in two days that *a reference to a name that does not exist* has gone through every gate silently (the other two: `var(--x)` naming an undefined token, and `into` naming an undefined variable). The check now also verifies that every `data-i18n` reference resolves, and a mutation test confirms it fires: delete one key's definitions and the old check still reports `sync=OK` while the new one exits 1.
- **A full-surface colour audit: 25 places failed AA, now none do.** Three times in ten days the same family of bug came back — the whiteboard stickers rendering dark under the light themes, bare `.chip` as white-on-white, the subagent badge at 4.45:1 — and each time a human found it by looking. `doc_audit` asks whether a token has a value in all three themes; it cannot ask whether that value is *readable on the surface it lands on*, and those two questions are a whole cascade apart. So this round measured instead of patched: a probe walks every visible text element in all three themes, composites the background layer by layer, and applies WCAG. It found **25 failures, 15 of them in Classic Warm alone** — a solid-gold button with white text at 2.94:1, the sticky role badge at 2.87:1, `--err` used as a button fill at 2.77:1, and the diff line numbers, breadcrumb meta and lane ids sitting just under the line. All of them trace to four root causes, and the fix is one rule: **a colour token can only serve one light/dark relationship**. Three pairs got split apart — `--accent` (decoration) from `--brand-ink` (body text), `--err` (a red line on a dark card) from `--danger-solid` (a button fill), and the sticker's role badge into `--role-a-fg` / `--role-b-fg`, since one value was being asked to sit on both bright gold and deep green. Re-measured across six views, three themes and the expanded states: zero. The probe ships as `tools/contrast_probe.js`, and "checked on the dark card" is now explicitly not an acceptance criterion.
- **Fixed: a row's font size no longer leaks in from the card.** `44 steps` in the subagent header rendered at 16px next to 10px chips and an 11.5px name, because neither the header nor `.an-tk` set a size and the cascade handed them the card default — the same shape as the cluster row fixed hours earlier. The header sets its own size now, and "one row, one font scale" is a check in the probe: a row whose largest text is 1.3× its smallest, and is not a heading element, gets reported.
- **Fixed: the prompt-diff pane was reporting `into is not defined` instead of a diff.** The unreleased "recording pane goes single-select" change dropped `renderDiff`'s second parameter but left the last line still reading it, so the whole comparison built its HTML and then threw on the way into the DOM. Three gates let it through and it is worth naming why: `node --check` validates syntax and `into` is a perfectly good identifier; `check_refs` resolves *call names* and CSS classes, not free variable reads; and not one of the twelve selftests executes front-end JS. A sweep of every view — including list, detail, grep and DAG on a compacted day — found this one and nothing else. A gate for the whole class was measured and deliberately deferred: the naive static rule yields 500 candidates on this codebase (object keys, destructuring, `for...of`), and `check_refs` ships only at zero false positives.
- **The tool-run cluster rows stopped looking like they came from a different list.** `#12-13 [Write][Bash] 2 tool calls` carried a hardcoded `padding-left:44px` from the previous flex-based step row and never set a font size, so once step rows became a grid it was both misaligned and a size larger than everything around it. Both now share one `--sn-w` column width, one 12px size, and the visual de-emphasis is carried by color alone; a wide range like `#123-131` grows its own cell instead of colliding with the chips.
- **Subagent lanes are now blue, the same blue the timeline gives them.** A grey rule the same color as every other divider is not a signal that the subject changed; the lane now carries `--info` on its left edge, its badge and its agent name, over a 7% tint. The badge needed per-theme values of its own: `--info` as text on its own tint measures 4.45:1 and 4.22:1 under the two light themes — under the AA line — which is the third instance this month of a color that was only ever checked against the dark background. It now measures 7.12 / 7.71 / 7.31.
- **Fixed along the way: every tool-name chip in the analysis view was invisible under both light themes.** `.chip` carries no background of its own — it expects a modifier — so a bare `class="chip"` renders `--chip-default-fg` (white) on transparent. On the dark card that reads fine; on Classic Warm and Lab Daylight it is white on white, and the tool names in the step list, the tool clusters and the tree's "did" row had been rendering as blank gaps. They now use the same soft-tint token as the tree's mark labels, and repeated calls collapse into `Bash×4` instead of four identical chips crowding out the title.

- **An archive now says which machine and which version produced it.** A `.ccwa` sitting on the desktop cost a whole investigation: it was a *remote* machine's recording, nothing about it said so, and it was read as local evidence until three clues buried in the recorded traffic — drive paths, the username, `cc_version` — settled it. The manifest, which exists precisely so you can tell what an archive is without unpacking it, could not answer the question: there was no machine field at all, and `tool_version` was **empty in every pack and every archive this tool has ever written**. The cause was not the archiving path, as first assumed — `_tool_version()` read `_version.__version__`, an attribute that file has never defined (it defines `VERSION`, which is what `app.py` reads), and `getattr` with a default turned a wrong name into a silent empty string in the one field whose entire job is provenance. Archives now carry `host` (hostname only, never the username: archives get copied around, and a hostname separates two machines with far less to leak) and a real version, on **both** archiving paths; the identity is unpacked into the imported recording too, so it survives landing on the other machine; and re-archiving an imported source deliberately does *not* re-sign it, because signing someone else's evidence with your own name is the exact failure `sources/` exists to prevent. `GET /api/sources` reports this machine's `host` alongside each source's and archive's own, plus `foreign` (differs from this machine), the settings card shows it on every row, and importing another machine's recording says so in the toast. Anything archived before this reads "machine unknown" — **empty means it cannot answer, not that it is local**, and the label cannot stand in for it either: labels are typed by hand, and the real one on this desk is `164807`, a timestamp.

- **Snapshotting a recording from an imported source no longer 404s.** v0.4.15 gave every *read* surface a `source=<label>` parameter, but the backup path — which reads a recording before writing a snapshot — was missed on both ends: the UI sent no `source`, and `POST /api/snapshots` didn't forward one, so the id was looked up in the local namespace and came back `not_found`. Local recordings (empty source) were never affected, which is why this survived release day: it takes importing another machine's archive and then snapshotting from it to hit — a first real user did exactly that within a day. Both ends now pass `source` through, the API contract documents it, and the fix is verified against the original failing recording (without source: 404; with: snapshot created).
- **The list view is now a step-by-step brief you can actually read.** Long agent sessions (a hundred steps, subagents, walls of tool calls) made recordings a black box in practice: the old list rows were mechanical facts — chips and char counts with no "what was this step doing". Clicking "AI summary" now also generates a **brief for every step** (from that step's thinking + reply; model-invented step numbers dropped by the same whitelist that guards turn summaries), batched at ~8K chars per call so a hundred-step session costs a handful of small calls, cached into the same analysis file so reopening is free. Pure tool steps never see the model at all — consecutive ones collapse into a dimmed cluster line (`#12-18 [Grep×6 Read×4]`, "14 tool calls"), which is all there is to say about them. The view itself is now zero-click: thinking originals stay one drill-down away in the tree view (list = read the story, tree = dig the evidence), signals chips stay as the mechanical counterweight to the AI's wording, and a failed batch is announced instead of silently missing. *Tuned the same evening on a real 137-step run*: the first draft asked for "what was done" in ≤40 chars and beheaded both the briefs (an 80-char disk cap cut mid-sentence) and the raw material (thinking clipped head-only, losing the decision that sits at the end) — the task now explicitly demands *why, what turned up, what was abandoned* in plain language with no length limit (the disk cap is a 2,000-char runaway guard, not a content limit), and long thinking is clipped head-and-tail. Both analysis prompts (per-turn and per-step) are now editable in Settings → LLM, following the explain-prompt pattern: empty means built-in default, the injection-guard scaffolding stays internal, and the placeholder spells out the JSON format that a custom prompt must keep. Also fixed: the analysis file recorded an empty model name when one was configured.
- **The recording-analysis pane now analyses one recording — by name and by behaviour.** Pick-two comparison is gone from the GUI: the board is single-select (clicking another sticker switches the analysis target, clicking the selected one clears it), and the tab is renamed "Recording agent behaviour" to say what it actually analyses. The prompt-diff pane keeps its two-pick compare. What this costs is deliberate and written down: comparing two recordings by system / tools / messages face — the way to watch context rot — now has exactly one path left, `GET /api/snapshots/diff?face=`; no `face` value comes from the GUI any more.
- **The instruction-sources list now starts folded.** Measured on a real day (633 recordings, one archive), the list was flooded by harness status notices: `<total_tokens>N tokens left</total_tokens>` arrives once per turn as a role=system message — 13,058 entries that day, each with a different number, so the existing "merge identical content" rule cannot fold them — burying the sources that matter (the 16K CLAUDE.md, the repeated 421-char reminder, the 89K of tool descriptions). The card is now a collapsed `<details>` with the entry count on the summary line; collection logic, the API, and the in-app analysis context are untouched.
- **The whiteboard and its stickers are no longer a dark island under the two light themes.** Switching to Classic Warm or Lab Daylight left the analysis view's board and stickers dark: a dimmed board, dark-brown paper, white text on it. The whole family (added 260808) had its colors written directly into the components — the paper gradient, the tape across the top, the folded corner, the drop shadow and the inner highlight — not one of them going through a semantic token, and `doc_audit`'s token check was silent about it: that check asks "does every token defined in the dark block have a value in classic/light", and this family **never defined a token at all**. All four layers are tokenized now (swapping only the paper color would give you light paper with a black folded corner, which is worse than not swapping), and each light theme gets paper of its own: cork board with cream/mint/blush notes for Classic Warm, a cold mineral board with clear-toned paper for Lab Daylight, while the recording snapshot keeps the cool-color gap that makes it distinguishable at a glance. Text contrast on paper is computed against **the least favorable of the four papers**: body, secondary, timestamp and category label all pass AA in all three themes (the last two used to sit at 3.9–4.1:1 even in dark — copying that hierarchy is what dragged both light themes under the line). Fixed alongside, same family of debt: the gold tint on list-row hover (which fights a cold theme), the four signal chips, the fork color in the tree view, the hardcoded slate `thinking` badge, the toggle's off-state track (a white knob on a near-white track barely reads as a switch), and the inline character-level diff highlight (a 32% mix is nearly invisible on light paper — and it is the only cue for *which characters* changed).
- **Referencing a CSS token nobody defined now blocks a release.** The analysis view used an older naming (`--text` / `--text-dim` / `--bg`) that this token system never had: 21 references resolved to nothing. That is neither an error nor a fallback to a default — **the whole declaration is dropped and the color silently inherits from the parent**, so those tiers disappeared in all three themes while the UI still looked "colored", and nobody noticed for over two weeks. `tools/doc_audit.py` gained a hard check: a `var(--x)` naming a token nobody defines, with no fallback written, blocks the release, and `--self-test` builds a counter-example to prove the check actually fires. References that do carry a fallback are not in this class (they have a defined degradation), but the redundant ones were cleaned out while we were here: `var(--mono,ui-monospace,…)` had been quietly degrading to the system Consolas, bypassing the "fonts are bundled so the product looks the same across platforms" convention.

## v0.4.15 - 2026-08-25

- **The 20K input cap on translate / AI-explain / the analysis chat is now yours to set.** Two module-level constants (`LLM_INPUT_MAX`, `CHAT_CONTEXT_MAX`, both 20,000 characters) decided where long inputs got cut, and nothing could change it — yet a single recorded system prompt is routinely 40K+ characters, so the "translation" or "analysis" you got back was of half the evidence. Truncation has announced itself since 260801 (`input_truncated` in the SSE stream, a gold notice in the UI); what was missing was letting the user choose where the cut lands. Two settings now live on the Translate/AI card, in **characters** (not tokens — the client cannot count tokens, and the truncation notice reports characters, so the setting and the notice share one unit): `input_max_chars` for single-turn translate/explain/diff-explain, `chat_context_max_chars` for the snapshot context injected each analysis-chat turn. Both default to the old 20,000 — an existing config.json behaves identically until you touch them — and both clamp to 1,000–2,000,000 on read *and* write, because this is a knob that spends money: zero would truncate to an empty string while still claiming "truncated", and a mistyped billion would burn a request. The cut notice's tail no longer says "raising max output tokens won't help" (it was true, and useless); it now names the setting that actually moves the cut. The internal share budgets (sources list, history window, per-question cap) stay fixed on purpose — opening every internal allocation is knob soup; what users actually hit was these two walls.
- **The HTTP API now has a human-readable face.** This tool has always been dual-mode — humans use the GUI, AI uses the HTTP API — but the two sides were separated by a wall: the only route returning HTML was `/`, every `/api/*` returned raw JSON, and `/api/ai-guide` returned raw Markdown. So after you copied that one line to your agent, **what the agent actually reads was invisible to you**. A tool whose whole premise is "never silently drop anything" was not inspecting its own output surface. Now `GET /view` lists every GET endpoint — grouped, one line of explanation each, one click each — and appending `format=html` to any GET endpoint renders it: JSON as a folding tree (arrays of like objects become a horizontally scrolling table), and the guide as a typeset document. **Without `?format=html` the response is byte-identical** — a selftest holds a baseline and compares byte for byte, because the AI channel is the other half of this product and a stray field or a reordered key is contract drift to whoever consumes it. The endpoint list is read from `app.url_map` rather than hardcoded, so a new endpoint appears there by itself; endpoints that need a path argument, plus `/api/captures/stream` (a long-lived SSE) and `/api/update/check` (hits the network), are listed but deliberately not clickable, with the reason spelled out on the row — hiding them would give the browse page a blind spot of its own.
- **The detail view stopped silently cutting tool calls in half.** `tool_use` inputs were rendered through `JSON.stringify(...).slice(0, 1500)`: a hard cut with no expand button and no notice, while the `bigText` component sitting right next to it has offered "show all (N chars)" the whole time. Measured across six days of real recordings, **10.6% of `tool_use` blocks exceed 1,500 characters**, and the longest — a `Write` on 2026-08-15 — is **37,257 characters, of which the UI showed 4% and said nothing**. One in ten tool calls was being misrepresented in a tool built to reveal exactly this kind of thing. All of these now fold with a full-text toggle; list caps that dropped items outright (`web_search` results past the 6th, citations past the 8th) are gone, and the per-line character cuts that remain end in `…` so the cut is at least visible. Fixed alongside: those same paths escaped their text and then handed it to `bigText`, which escapes again — any title containing `&` or `<` was displayed double-escaped as `&amp;lt;`.
- **Recordings can now be compacted in place, archived into one portable file, and imported from another machine.** Claude Code re-sends the whole conversation on every turn (that is what prompt caching is), and this tool writes each request out in full — so on a measured day (2026-08-09, 477 MB, 855 requests) **75.4% of the bytes are `messages`, of which only 6.6% is unique content**, and the tool definitions resent on all 855 requests hold 0.13 MB of unique content while occupying 84 MB of disk. The old "archive" action compressed that with zip DEFLATE, whose 32 KB window cannot see repetitions that sit megabytes apart — measured 2.6x. Compaction instead content-addresses every top-level block of `system`/`tools`/`messages`, stores each unique block once as its own zstd frame, and leaves the record skeleton pointing at integer blob ids: **that same day goes to 14.8 MB (33.9x)** while a single record still opens by random access (median 17 ms, p90 27 ms). Reading is unchanged — for any given date, list / DAG / detail / grep return byte-identical results before and after compaction; only `/api/stats` differs, in the three fields whose meaning *is* "how much space this takes now". Nothing is deleted: `uncompact` restores the original file byte-for-byte, and compaction only removes the original after verifying a full byte-for-byte reconstruction of the entire file first.
- **The three storage actions are now distinct, in code and in the UI.** *Compact* shrinks in place and deletes nothing. *Archive* writes one portable `.ccwa` file and, by default, keeps the original. *Clear* is the only thing that deletes, and retention is the only thing that deletes automatically. Before this release the single menu entry "clear and archive" conflated the second and third, and the storage dropdown now spells the difference out per action. **Today is never compacted** — `append` is writing to it, and proxy transparency outranks disk space; the guarantee is structural (compaction only ever processes past dates), not a lock.
- **Recordings from another machine open in this one.** `archive` produces a single file you copy across; `import` unpacks it into `sources/<label>/`, a namespace of its own, because two machines recording on the same day will always collide on the date — and the failure mode of mixing them is not an error message, it is reading another machine's evidence as if it were local. Every read surface takes `source=<label>` (`--source` on the CLI), `GET /api/sources` lists what is imported, and the capture page grows a source switcher whose selected state is deliberately loud.
- **Fixed along the way**: an empty `?date=` was treated as a real (non-existent) date rather than "not given", which showed an empty list for a day that had records and reported no error at all; `tools/check_i18n_js.py` crashed instead of reporting when `node --check` failed on a line containing CJK text (it read the pipe as GBK), so the syntax gate failed exactly when it was needed; and `cli_selftest`'s retention assertion hard-coded a date that stopped being "recent" on 2026-08-11, so that check had been failing for two weeks on a date-dependent premise rather than on the behaviour it meant to test.

## v0.4.14 - 2026-08-10

- **The identification system is now written down as one map instead of a dozen scattered heuristics.** How this tool decides "what kind of call is this / who started this turn / who spawned this subagent / which main line does this auxiliary belong to" is seven layers deep, and the new §2.6 of `docs/reference/开发约定.md` lays them out in one table — what each layer decides, which official Claude Code identifier is authoritative for it, and what the heuristic fallback is. The point of the map is the one row that stands out: **turn origin is the only layer with no official identifier on the wire**, which is why Claude Code's self-authored turns (suggestion completions, away recaps, internal search dispatches, background notifications) are matched by a wording whitelist and not by structure — every structural discriminator tested (`tools_n`, `max_tokens`, billing-header version hash) overlaps completely with real human turns. That also fixes the direction of the safety margin in writing: an unrecognised turn always falls back to `user`, because showing a synthetic turn as main is cosmetic while demoting a real human turn is not. The agent-facing manual gained the matching section — an agent reading `/api/dag` previously had no way to know `turns[].origin` existed, and would have counted machine-authored turns as user questions — plus a correction: the interactive-mode (`cc_entrypoint=cli`) subagent gap it still warned about was closed by a live captured session, so that warning is gone from the manual and from the Next steps above.
- **Turn origin has been measured against ground truth for the first time, and it found a field we weren't using.** The wording whitelist that decides "human or Claude Code talking to itself" had never been checked against anything — it was designed to look right. A new development-time probe (`tools/origin_probe.py`, not shipped in the binary) joins recorded traffic against Claude Code's own local conversation logs, which carry a `promptSource` on every user message, via two joins anchored on official ids on both sides. Across 8 days and 2,339 judgeable turns the heuristic agrees **99.8%** of the time, and the direction that actually matters — a real human turn demoted to "synthetic" — happened **0 times**. The four turns it did miss shared no wording at all (a script can send anything), but all four carried `cc_entrypoint=sdk-cli`, with zero false hits across 2,180 human turns: so `origin` gained a fifth value, `sdk`, decided by that official header rather than by guessing. Two numbers worth carrying: on turns whose first request succeeded, **45% are Claude Code talking to itself** and only 50.3% are human; and turn counts are wildly inflated by retry storms — one recorded day had 2,049 "turns" of which 2,000 began with a 504, covering three real questions. Filter by status before you count anything per turn.
- **Public presence launched.** Bilingual English/Chinese GitHub Pages site (canonical, hreflang, Open Graph, SoftwareApplication JSON-LD, sitemap), a 1280×640 social preview, and Google Search Console ownership verified. Three READMEs refreshed with the full product name, real `git clone` and `releases/latest` entry points, and platform/local-run trust signals (`c64dbe7`, `216b10d`). Community promotion deferred. The from-scratch reproducible tutorial lives in `promo/` (gitignored, local only).## v0.4.13 - 2026-08-09

### Fixed

- **The in-app updater's Download button is no longer a leap of faith: locked single-flight + immediate feedback.** On v0.4.11, clicking Download looked dead for several seconds — the checksum-manifest fetch and the GitHub connect (both seconds through a proxy) all happened before any progress phase existed; worse, the progress poller treated that pre-connect window as a terminal state 500ms in and stopped, reverting the UI to an untouched-looking Download button that invited re-clicks — and every re-click passed the hollow duplicate-check and spawned another download thread. One real session fired **13 concurrent download threads writing the same `.part`**; the first finisher's rename then tripped over its own siblings' file handles, surfacing "the file is in use by another process" (WinError 32) — the file was held not by some other program but by our own threads.

  The fix gives each layer its own job: the backend registers the task under a lock as a `starting` phase *before* touching the network (repeat calls get `already_running`, and the UI reattaches the progress bar to the running task instead of erroring); the staging file name is unique per attempt (defence in depth — should the guard ever be bypassed again, two writers never share a file, so rename can never hit a sibling's handle); the frontend disables the button and optimistically renders the `starting` progress bar on click. Two adjacent bugs fixed along the way: checking for updates mid-download no longer clobbers the running task's phase back to `idle` (which used to stop the poller), and the checksum-manifest fetch moved from the request handler into the download thread (it was part of the silent seconds). Verified end-to-end with real clicks: five rapid clicks spawn zero extra threads, a mid-download update check leaves the progress bar alone, and the install entry appears once SHA-256 verification passes.

  **Upgrade guidance for v0.4.11 users**: the old version's updater UI carries this bug (the fix ships in the new version), so the reliable path is "Open releases page" and swap the file manually; or click Download **once** and wait patiently (the download is genuinely running — the UI just won't tell you), and do not re-click.

## v0.4.12 - 2026-08-09

### Added

- **The sequence diagram now distinguishes who started a turn — and folds turns and their auxiliaries manually.** This is the third of a five-step rework (`issues/closed/260809_时序图折叠语义与手动折叠.md`), preceded by a comparison against Claude Code's own `~/.claude/projects/*.jsonl` (six sessions, 82 main-lane turns).

  **About 37% of "turns" on the wire are not from you.** Turn boundaries were cut by one rule — "the last user message has a real text block" — but Claude Code synthesises pseudo-user messages (`[SUGGESTION MODE …]`, `The user stepped away …`, `Perform a web search …`, `[SYSTEM NOTIFICATION …]`) that satisfy the same rule, so a quarter to a third of the turn cards were CC talking to itself, drawn identically to ones you typed. There is **no structural discriminator on the wire**: `tools_n`, `max_tokens` and the billing-header version hash all overlap between human and pseudo turns, so a text-prefix whitelist is the heuristic — but jsonl carries authoritative `origin.kind` / `promptSource` markers that never cross the wire, so the whitelist was validated against ground truth first: of the 11 main-lane requests wire has and jsonl lacks, 10 are exactly the whitelist hits (the 11th is an interrupted human message). Turns now carry an `origin` (`user` / `synthetic` / `command` / `partial`); synthetic turns are drawn as a faded dashed card labelled "CC auto:" rather than merged or hidden — they trigger real work and real token cost, and hiding data the wire actually carried is failure mode ③. The whitelist falls back to `user` for anything it does not recognise, since mislabelling a human turn as noise is worse than mislabelling noise as human. One divergence kept deliberately: turns that open with an image paste stay `user` — jsonl marks those `isMeta` and does not count them as human prompts, but the timing shows eight consecutive pastes each driving 3–25 steps of real work, which is the human advancing the conversation. That is jsonl's blind spot, not ours.

  **Auxiliary aggregation now groups by turn, not by lane.** It used to key on the associated main lane, so a day with 2–4 lanes produced 2–4 aggregate cards and clicking one expanded that lane's entire day's auxiliaries (90+ requests on 08-09) with no middle level — yet the backend already attributes every auxiliary to its turn. Grouping by turn yields 25 cards for the same day, one "turn N · aux ×k" per turn; auxiliaries that map to no turn stay single (no silent drop). The turn card's aux badges are now clickable to fold/unfold that turn's auxiliaries in place. The whole loop was verified with real clicks, not scripted function calls — the collapse badge on an expanded aux group is pinned to the group's first *visible* member (`DG.auxFirstVisible`), because the nominal group head can be filtered out by "hide tool-loop steps", and then there is nothing in the DOM to click to fold the group back.

  The comparison also surfaced the join key for the 0.6.x "wire ↔ jsonl" roadmap item: `response.headers_safe["request-id"]` matches jsonl's `assistant.requestId` exactly — 432/432 = 100% on 08-09. The first consumer is planned as a ground-truth override for this origin heuristic (when jsonl is present, its `origin.kind` wins). Two things to carry forward: wire stores local-naive timestamps while jsonl is UTC, and only Anthropic upstreams return `request-id` — the GLM/Kimi upstreams you alternate with answer `x-log-id` and cannot be joined this way.

### Fixed

- **A residual turn (recording started mid-turn) can now be folded back after expanding.** Expanding a partial turn used to leave no way to collapse just that turn: the turn-collapse badge was pinned to `t.head`, but a residual turn's head has `turn_start=False`, which `dagTierOf` demotes to the slim "mid" row — and the `mid` branch returned before reaching the badge. On 08-08 a 137-step residual turn expanded into 137 cards recoverable only via the global button, which also resets every other turn's expansion. The badge now rides the turn's first *visible* member (`DG.turnFirstVisible`, precomputed in the same order as the tier/hideMid filters), so it always lands on a card that actually renders.

- **Settings now lists every running instance with its port, mode and recording state.** `serve` is doubly windowless — the build is `console=False`, and the `serve` branch never creates a pywebview window — so an instance can hold a port and run all day with nothing on screen to show for it. That is exactly what happened: a stale `serve` from an older build sat on port 5053 for seven hours while the real recording ran in a GUI on 5051, and it only surfaced because its own `.exe` refused to delete. Task Manager shows the process name but not the **port**, and the port is the one number that matters here — whichever one `ANTHROPIC_BASE_URL` points at is the instance that is actually recording. The card marks idle instances explicitly, since "running" and "recording" are not the same thing and the gap between them is the whole failure mode.

  Discovery is a live port probe over `5051-5100` (`GET /api/instance`, new), **not** a read of `port.txt` / `serve.pid`. Those files are single-copy, last-writer-wins, carry no instance identity and are never cleaned up on exit — measured the same day, `serve.pid` still held a PID that had exited six days earlier, and PIDs get recycled. Answering HTTP proves something stronger than a live PID anyway: not "a process exists" but "an instance can do work". Because nothing persistent is involved, this view cannot go stale. Instances from older builds are still found via an `/api/about` fallback and flagged `legacy` (verified against the running v0.4.11). Scanning all 50 ports takes 0.18s (0.48s before the probe went fully concurrent). The port range is hard-coded and takes no parameters — an unauthenticated local endpoint that accepts a port range is a local port scanner — and the probe bypasses the system proxy, which matters more here than most places given what this tool does to `ANTHROPIC_BASE_URL`.

- **The turn skeleton gained an AI semantic layer: what each turn is doing, what it wants, and what is worth watching.** Click "AI turn summary" once; the result is stored, shown directly on later visits without paying for it again, and re-runnable via "Summarise again". It uses the low-cost model already configured in Settings.

  **This is layering, not handing the skeleton to the AI.** The factual layer — which steps exist, what triggered them, which tools were called, where the turn boundaries are — is still extracted from the recording by code and can be recomputed; the AI only annotates turn boundaries. The reason is that wire-level truth is what this tool exists for, and putting "what actually happened in this conversation" in the hands of a component that hallucinates replaces the foundation with the model's good intentions. So the backbone on screen stays the program skeleton, and the AI lines carry an "AI" badge — when it gets something wrong you can check it against the factual rows right below it.

  The critical piece is that **the backend validates the step numbers the model cites**: anything absent from the program skeleton is dropped and reported in `dropped_steps`. Telling the prompt "only cite real step numbers" is a request, not a guarantee — without that check, "the AI summary is anchored to program facts" is just a claim: the model can summarise a turn made of steps that never existed and the UI will render it just as convincingly. Results live in `<sid>.analysis.json` rather than the snapshot envelope, because the envelope is immutable (a snapshot's value is that it does not change) while this is a recomputable derivative that re-analysis overwrites; it is deleted with its snapshot and counted in what cleanup says it can free.

- **Settings now shows what the recordings cost on disk.** A tool that writes continuously should say how much it has written; until now that number existed only in the data directory. The card breaks out recording bodies, the write-time index, archives, snapshots and the run log, plus the day count and the largest single day — measured here at **4.81 GB over 15 days, with 1.10 GB in one day**, which is the concrete version of the "single day can reach GB scale" note behind the 0.5.x storage work. Display only: no cleanup or archive buttons, because both already exist on the Captures page and a second entry point for deleting user data is how the two drift apart.

  **The endpoint only ever calls `stat`, never reads a file** — that is a contract, not an implementation detail. Cost must scale with file *count*, not data *volume*: `scandir` over 4.8 GB is 1.12 ms steady-state and stays 1.12 ms at 100 GB, whereas counting entries means reading lines (4.4 ms per day and growing, or 4.8 GB if read from the bodies via the existing `list_capture_dates`). That is also why the card shows no entry count: it is the one field that would make this view slow down as recordings accumulate. Being that cheap, it needs no cache either — a TTL would only add "this number is a few seconds old" as a new failure mode. `fmtBytes` grew a GB tier while we were here, since `4852.8 MB` asks the reader to do arithmetic.

### Fixed

- **The delete button on board stickers is now actually clickable.** Clicking × did nothing, and not intermittently. Three causes were stacked on top of each other and only the outermost was visible: on a selected sticker the role badge (left / right / analyse) overlaps the ×'s rectangle and has a higher `z-index`, so it won the hit test. **But even with no badge at all, delete still failed entirely** — `mousedown` is bound to the whole sticker, × is inside it, and on `mouseup` the "didn't move ⇒ select" branch calls `anPick()`, which re-renders the board; the button carrying that click gets replaced via `innerHTML` before the browser can dispatch `click`. **The button was not broken — it was swapped out of the document before the click landed.** The badge now sits top-left with `pointer-events:none` (it is pure decoration and should never take part in hit testing), and `mousedown` ignores events originating in the × or the confirm overlay. This bug cannot exist in automation: calling `anAskDelete()` directly passes every time, because a function call goes through neither the hit test nor the "is this element still in the document" check — **verifying an interaction defect means actually clicking the element**.

- **Newly saved snapshots no longer land underneath older stickers.** The report was "I saved a prompt, switched to Analyse, and the board looked unchanged — I had to hit Tidy up before the new one appeared". Auto-placement put the *i*-th unplaced sticker in the *i*-th grid slot **without checking whether a manually positioned sticker already occupied it**, so once the old stickers had been dragged into place, every new one landed on (22,22) — directly under the first. Placement now skips occupied slots by rectangle intersection, which also preserves the original intent (after you drag a sticker away, the next new one should fall into the freed slot rather than queue up at the end): a freed slot is simply no longer occupied. Measured with old stickers on (22,22) and (274,22), the new one lands on (526,22) with zero overlap.

- **`doc_audit` no longer fails the release gate over another tool's endpoint.** It flagged `/api/anthropic/v1/messages` as a ghost endpoint — but that path belongs to zcode, quoted in the guide on building this kind of analyzer *for other agent tools*, where writing down the target tool's endpoints is the point of the document. A permanently red gate is worse than no gate: it ends with someone adding `|| true` in CI, and the check stays hanging there pretending to be a defence. The fix is an audited `EXTERNAL_ENDPOINTS` allowlist (same shape as `KNOWN_BETAS` — hard-coded, one entry at a time, each naming which tool it belongs to), **not** skipping `docs/methodology/`: 4 of the 5 endpoint references in that directory are real endpoints of this project, so exempting the whole tree would trade one false positive for four lost checks. The allowlist is itself checked from both ends — an entry no longer cited by any document fails the self-test as dead, and an entry that becomes a real route fails the gate as a stale exemption that would otherwise silence the audit for that endpoint. Verified by mutation: a planted `/api/definitely-gone-endpoint` still fails the gate, so the exemption did not widen the rule.

## v0.4.11 - 2026-08-09

### Added

- **"Check for updates" now finishes the job: download, verify, replace, restart.** It used to compare tags and print an address — the notification was done and the six laborious steps (write the address down, open a browser, find the asset, download it, close the running program, overwrite it) were all left to you. The whole pipeline now lives behind `/api/update/*`, so an agent can drive it too, and so the front end and back end cannot return two different answers about what the latest version is. **This is "one click and it is swapped", not "auto-update"**, and the distinction is not wording: this tool holds a patch on your `settings.json` while recording, so there is no timed check and no silent install — every step is a click, and **applying an update while recording is refused rather than stopping the proxy for you**, because stopping writes your settings.json back and that is not something the intent "I want to upgrade" should trigger in passing. Windows replaces in place: the running exe cannot be written to but **can be renamed**, so the sequence is stage into the same directory → rename the old one aside → move the new one in, with any step failing rolling the whole thing back — this is the only path in the project that touches an executable on the user's disk, and if it goes wrong the user is left without a working program. macOS deliberately stops at download-verify-reveal-in-Finder; the maintainer is on Windows, and replacing a running bundle also involves quarantine attributes and Gatekeeper. Being the first path here that **downloads and executes a binary**, it became safety invariant 10: the source repo is hardcoded (a configurable download address turns an unauthenticated local HTTP endpoint into "make this machine download and run an arbitrary binary"), https only with **every redirect hop** checked against a host allowlist (a release asset always redirects to object storage, so checking the first hop only is checking nothing), and the checksum is compared when the release ships `SHA256SUMS.txt` — when it does not, the panel **says so and shows the measured digest** instead of quietly downgrading to "transport security only". The self-test caught a real one: a failed download used to leave the previous, same-named package sitting in the updates directory, which is the worst possible residue — a plausible-looking exe of unclear provenance waiting to be double-clicked.

- **The version is now visible without opening the program.** It only ever lived at runtime (`/api/about`, `--help`), so a downloaded exe had an empty "File version" in its properties and the only way to tell two builds apart was to double-click one — not a free action for a tool that patches `settings.json` on startup. The same `src/_version.py` that CI generates from the tag now feeds four outlets: the API, the Windows PE version resource, the macOS `Info.plist`, and the release asset file name (`cc-wire-analyzer-v0.4.11-windows.exe`). **The two spec files share `tools/version_res.py` rather than each carrying a copy** — they have diverged once before, when the macOS spec missed `brotli` and every non-streaming response lost its body on macOS; a shared module makes divergence structurally impossible, which beats adding a check that someone must remember to run. `doc_audit` still backstops it: whichever spec drops the import blocks the release. Release builds also ship `SHA256SUMS.txt`, which is what the in-app updater verifies against.

- **`tools/build.py`: local packaging with the same version / naming / checksums as CI.** `uv run python tools/build.py` produces `cc-wire-analyzer-v<version>-<platform>.exe` + `SHA256SUMS.txt`, matching what CI ships — the naming rule and the checksum glob previously lived only in `release.yml` (bash), and two languages each carrying a copy of a string-concatenation rule is exactly the shape of bug ⑦. `--from-git` reads the version from `git describe --tags`; `--self-test` independently reconstructs the expected file name and compares it against the function, so either side changing without the other will fire.

### Fixed

- **Switching the UI language now refreshes an already-rendered snapshot diff on the Analyse tab.** The comparison result — verdict line, tool buttons, hidden-difference table, body header — is built by `renderDiff`, which bakes `t18()` strings into the DOM as plain text (no `data-i18n`), so `applyI18n()` never reached it; switching language left it stuck in whatever language you ran the comparison in, until a page reload. The same gap the settings page hit on 260801 (`renderSettingsI18n`), only this time on the Analyse view that shipped in v0.4.10 — the 260801 lesson is written into the dev guide, but a text rule cannot stop a brand-new view from missing the rerender. `renderDiff` now caches its result per pane (`AN.pDiff` / `AN.rDiff`), and `setLang` re-renders from the cache when the pane still has two snapshots selected — selection state is the cache's validity guard, so a stale diff cannot be revived after the selection changes. No new API call, no flicker.
- **The comparability-guard warnings in a snapshot diff now follow the UI language too.** Those warnings ("different request types", "the identity fingerprints differ — these were never two versions of one prompt", "different models"…) were hardcoded Chinese in `snapshot_diff.py` and rendered verbatim, so they stayed Chinese in every language — the same shape of gap as the entry above, only the text lived in the backend. `renderDiff` now maps each warning's `field` to an `an.guard.<field>` i18n key (three locales, five fields) and falls back to the backend `why` only if a key is missing; the backend text is kept verbatim for HTTP-API consumers (agents), so no API contract changed. Backend unchanged.

- **The update relaunch now restores settings.json *before* spawning the new process.** The order used to be Popen → restore → exit, relying on the new process being slow to start (cold start 1–2s) while the restore is microsecond — a timing assumption, not a sequencing guarantee. If the new process (serve mode, which auto-patches `settings.json` on startup) ever won that race, the old process's restore would undo the new process's patch. The order is now restore → Popen → exit, all within one thread, so the sequencing is deterministic. The fix was exposed by a separate one: a variable renamed `on_exit` → `restore_fn` left a stale reference in the `Timer` line (`py_compile` does not catch it, `node --check` does not exist for Python — bug ⑥ on the Python side), which surfaced when a real e2e apply was run for the first time.

- **Local `uv run pyinstaller` builds crashed in serve mode with `PackageNotFoundError: werkzeug`.** Werkzeug 3.x calls `importlib.metadata.version("werkzeug")` in `BaseWSGIServer.__init__`; PyInstaller's auto metadata hook misses the `.dist-info` under uv's venv layout (hardlinks rather than standard site-packages). CI is unaffected (standard `pip install`). `version_res.runtime_metadata()` now collects the six dist-info directories (werkzeug / flask / click / jinja2 / itsdangerous / markupsafe) and both spec files append them to `datas` — shared, like the version resource, so the two specs cannot diverge.

## v0.4.10 - 2026-08-08

### Added

- **Snapshots: back up a prompt or a whole recording, then compare them down to the codepoint.** A fourth tab, Analyse, joins Captures / Timeline / Settings, and each of its two sub-pages is a **board** — what you backed up sits on it as a sticky note you can drag, and clicking notes is what starts an action. Prompt notes live on the prompt board and recording notes on the recording board, never mixed; picking two prompts diffs them, while on the recording board picking **one** analyses that recording and **two** compares them along a chosen face (system / tools / conversation history — that last one being how context rot becomes visible). Note positions are stored **on the snapshot** rather than in the config, because where a note sits is the user's own organisation of that set, and deleting a snapshot should take its position with it instead of leaving an orphan coordinate pointing at nothing. The entry point is deliberately *not* on that tab — you right-click in a capture's detail view, where you are already reading the thing you want to keep. The decisive measurement came first: a single late request already carries the **entire reasoning chain of the conversation so far** (CC replays historical `thinking` blocks in `messages` — the largest sampled request holds 66 blocks and 314,286 characters), so a snapshot unit is one request, not a session; packing a session would store the same history dozens of times over. The two snapshot kinds get deliberately **asymmetric metadata**: a recording snapshot keeps a thin envelope because the record already holds id/timestamp/model/upstream/billing header, and a parallel copy is this project's documented rot cause #1; a prompt snapshot is a fragment torn out of context, so it carries four metadata groups — where it came from, which record, under what conditions, and its fingerprints. Six of those fields exist because without them a difference cannot be *attributed*: the **upstream vendor** (the same CC through a gateway versus the official endpoint genuinely has different prompts), the **`agent_fp` identity hash** (two snapshots with different hashes were never two versions of one prompt — it doubles as a comparability guard), `wire_kind`, the declared `beta` set, the **block shape** (a prompt "changing" is sometimes blocks being split or merged, invisible if you only look at one block's text), and a **normalised fingerprint** that erases dates/times/UUIDs — without it, CC's embedded current date makes every day's snapshot differ from every other and the real changes drown. Snapshots are never touched by `retention_days`, following the rule `archives/` already set: what the user explicitly saved is never deleted automatically — so the Analyse tab shows total disk usage, because "it just accumulates" must at least be visible.

- **You can now argue with the built-in model about a snapshot, turn after turn, and the argument is kept.** `POST /api/analyze/chat` streams a multi-turn conversation about one snapshot; the transcript lands next to it in `snap_xxx.chat.jsonl` and is readable over HTTP, so an external agent can see what the cheap in-app model already worked out instead of starting from zero — and so can the user tomorrow. Preset questions **switch by availability tier**: "which branches did it consider" only appears when there is a reasoning chain to answer from, and the tier-B system prompt carries a hard ban on describing what the model was thinking, with the specific reason quoted into it. Letting the model work that out for itself is unreliable, and we already know the answer, so it is written in. Three things follow from multi-turn that single-shot `/api/explain` never had to face. The snapshot context is **recomputed from the snapshot each turn and never persisted** — the snapshot is immutable so recomputation is deterministic, whereas persisting it would bloat every transcript with a 20K block and bury the actual conversation an agent came to read. The **guard is reassembled every turn** rather than trusted to the model's memory: untrusted recording text sits in the history from turn one, and by turn five a model can be well inside the role it was handed. And when history exceeds its budget the oldest turns are dropped **with a line telling the model they were dropped** — otherwise it assumes it can see the whole conversation and says "as we established earlier", which is the same failure the difference report's truncation notice exists to prevent. Persistence happens *after* an answer is produced: a missing API key should not leave a trail of questions nobody ever answered, while an answer cut off midway is stored **with its interruption reason appended**, because half an answer filed as a whole one is something the next turn will build on as settled.

- **A bulk cleanup entry, the counterpart to "snapshots are never deleted automatically".** `retention_days` deliberately never touches `snapshots/` — what the user explicitly saved is not for a background job to remove — and the cost of that decision is accumulation, so the manual exit has to exist. Filter by kind, tag, or date (conditions are ANDed), **preview what matches and how many bytes it would free, and only then confirm**: deleting by tag cannot be undone, and a one-click button for it would eventually take something it should not. A failed deletion inside a batch does not stop the batch and is reported back by sid — stopping halfway leaves the user knowing neither what went nor what remains.

- **The hidden differences now say *where* they are.** The census reported "ZWSP 0 → 1" and stopped there, which is the least useful place to stop: these differences are by definition invisible, so telling someone one exists somewhere in three thousand lines is telling them to search for something they cannot see. Each row now carries line-number buttons that scroll to the occurrence and flash it. The index is built from the same pass that renders the body, so the sentinel names in the census and the sentinels in the text can never drift apart.

- **A verdict from the built-in model, and translation, on the comparison itself.** `POST /api/snapshots/diff/explain` streams an assessment of what the differences mean — which are substantive rule changes and which are noise, what the metadata suggests caused them, and what a homoglyph difference implies (that kind is rarely typed by a human). It deliberately **does not send both full texts**: two 7K prompts alone exceed the input ceiling, and the question being asked is answered by the differences plus the metadata, not by re-reading the fifty-eight lines that did not change. The report is assembled server-side, is truncated against its own budget, and **says so inside the report when truncated** — otherwise the model would conclude "that's all of them" from a partial list.

- **A diff that shows the differences you cannot see.** Prompt differences are frequently invisible to the eye — the known instance being CC's character watermark for Chinese users, which swaps `-` for `/` inside dates and the apostrophe for one of four homoglyphs. A general-purpose diff renders those as "two identical-looking lines flagged as different", and the reader concludes the tool is broken. So this one **reveals first, then compares**: zero-width characters, NBSP, ideographic space, CR, and trailing whitespace become visible sentinels (`⟨ZWSP⟩`, `⟨CR⟩`…) *before* `difflib` sees them, which turns an invisible difference into an ordinary textual one while leaving identical invisibles identical. Homoglyphs are handled the opposite way — they are already visible, so rewriting them would flood the page; instead the inline character-level diff tags them (`U+0027 → U+2019`, "apostrophe"). Getting the homoglyph census honest took two corrections: the first grouping put `:` and `,` in one bucket, so a genuine `:`→`,` edit was labelled a homoglyph substitution — **a wrong assertion is worse than none**, since the reader believes they have found a hidden watermark; and counting the baseline ASCII character meant every normal edit changed the space count and lit the warning, and a permanently-lit warning is not a warning. Groups are now pairwise-exact and skip their baseline character.

- **The step skeleton gained a tree view, and the signals gained colours.** The list answers "how big was each step"; the tree answers "where did it weigh something, and what did it do about it" — the spine is the step order, a blue dot marks a branch or self-correction, and under each node sit **the sentences that matched** alongside the tools that step actually called. Those sentences are what makes it a tree worth reading: a node saying "branch ×1" carries no information, while one saying *"I should ask which direction to continue, or check issues/open first"* followed by *actually ran: Glob, Bash* shows the choice and its resolution. The boundary is stated on the page itself: **these are mechanically detected candidates, not conclusions** — the model never wrote its decision tree down, and a keyword match is not proof it was deliberating. Signals are coloured by class (hesitation / branch / self-correction / uncertainty), which took one correction: the per-class colours had the same specificity as the pre-existing generic `.chip.sig` background but came earlier in the file, so all four rendered identically until the fallback was moved ahead of them.

- **Reasoning-chain extraction in three layers, with a budget that is actually enforced.** The input ceiling for the built-in model is 20,000 characters against a 314,286-character reasoning chain — a factor of 15, so mechanical compression is the whole feature, not a detail. L0 is a skeleton (one line per step: what triggered it, how much it thought, which tools, which mechanical signals), L1 an excerpt-per-step summary, L2 one step's full text. Excerpt space is **weighted by signal density** rather than split evenly — the question being asked is "where did it hesitate, which branches did it weigh", and an even split gives the pivotal step exactly as much room as the dullest one. The budget itself had to be gotten wrong three times before it was right, each time the same mistake: **estimating instead of measuring** (rows assumed at 60 characters were really 230; reply excerpts were added outside the measured skeleton; then the summary counters themselves were added after the final measurement). The output is now built, serialised, measured, and shrunk in a loop, and reports `size` / `budget` / `over_budget` truthfully rather than claiming to have stayed inside.

- **Three tiers of availability, because "no reasoning chain" is normal, not an edge case.** Measured across 1,000 requests: claude-sonnet-5 tier is `thinking: disabled` in **23 of 23** cases, glm-5v-turbo has reasoning in 1 of 44, while glm-5.2 / k3 / opus-5 sit at 63–89% — and `adaptive` is the dominant mode, meaning **the same model reasons on some steps and not others**, so the judgement is made per step, never per model. Tier B falls back to a **behaviour chain** (tool sequence plus repetition evidence: the same tool in a row, the same target repeatedly, retries after errors) and states the specific reason rather than showing an empty panel. The line it must not cross is written into the prompts themselves: behaviour answers *what it did and where it went in circles*, never *what it was hesitating about* — handing a model only tool logs and asking about its state of mind is an invitation to invent one, so the B-tier prompt forbids it and drops the "which branches did it consider" question entirely. Tier C marks upstream-encrypted `redacted_thinking` without pretending to parse it. A related caution surfaces when a tier-A capture also contains encrypted blocks: "it never considered X" may only mean that part was unreadable.

- **The instruction-source list, which is where conflict analysis has to start.** Not "read everything and look for contradictions" — a single main-line request was measured to carry **five** separate places issuing instructions (three system blocks, the injected user CLAUDE.md, and a mid-conversation `role=system` message), plus tool descriptions totalling 81,911 characters, **thirteen times the system prompt itself**. Identical repeated injections are merged into a count, because "the same rule was injected nine times" is itself the finding — it crowds the context, and the repetition may be why the model stopped honouring it. This also settled a design question: prompts do not live only in `system`, so snapshotting supports system blocks, message blocks, and free selection alike.

- **Nine HTTP endpoints and a copy button that hands another agent the keys rather than the data.** The full snapshot surface is registered in the API contract and the shipped `AI_USAGE.md`, so an agent on another machine can drive it without the repository. The copy button produces **instructions, not content**: this machine's real port, the endpoint list, the snapshot's metadata summary, and the analysis task — pasting 800KB of recording into a chat box neither fits nor allows follow-up questions, whereas an address lets the agent drill in on its own. The text switches by tier and comes in all three UI languages, and it lives in the backend because the endpoint list is a backend fact that would fork the moment it were copied into the front end.

- **`src/snapshot_selftest.py` — the seventh self-test, and it earned its place immediately.** It caught a real bug that manual verification had passed: environment extraction ran its regex over `json.dumps(body)`, where newlines are escaped and the whole body is one line, so `(.+)` matched several hundred thousand characters instead of one path. Real-data checking had "confirmed" this field twice — both times the printout was truncated before reaching it. Extraction now walks actual text values. The suite asserts the things most likely to fail silently: budgets genuinely held across four sizes, tier B producing a reason and a behaviour chain rather than a blank, watermark-grade differences being revealed, and — inverted — a genuine edit **not** being reported as a homoglyph.

- **`tools/check_refs.py` — a static audit that every front-end reference resolves.** Two checks, one idea: each JS call name must resolve to a definition (including calls inside HTML `onclick=` handlers), and each class used in static HTML must actually be matched by one of its own CSS rules. Both shapes bit in the same round: a success branch called `loadStatus()` when the real name is `refreshStatus()` (the ReferenceError threw the branch into `catch`, so the repair worked but its green receipt never appeared), and a note element carried `class="sub"` whose only rule is `.srow .sub` while the element sat as a direct child of `.scard` (wrong font size — the user spotted it). **Neither is a syntax error**, so `node --check` cannot see them, and the six selftests are all backend. Getting to zero false positives took two lexical stages: blanking strings and comments (47 → 24 noise) and then recognizing **regex literals** — a quote inside `/['"]/` opens a phantom string that swallows the rest of the file, which had 24 defined functions (including `toast`) reported as undefined. On the CSS side, a compound selector like `.turn-badge.sub` is *not* a bare `.sub` rule (its other classes are requirements on the element itself), and classes added at runtime via `classList.add` must be exempt or every state-styled element is a false positive. `--self-test` mutates the file in memory to recreate both real bugs and proves the checks fire.

- **Upstream config history, and one-click repair when a switcher tool freezes the proxy's local address into a provider.** The failure is a delayed one, which is why it was so hard to place: while recording, `ANTHROPIC_BASE_URL` points at `http://127.0.0.1:<port>`; if you switch providers at that moment, the switcher saves the *current* settings.json — local address and all — into the provider you are leaving. Nothing breaks then. It breaks whenever you switch *back*: Claude Code is now pointed at a local port nobody is listening on, and third-party tokens and the official subscription fail alike, while the config still *looks* fine. `docs/reference/AI_USAGE.md` has warned about this since 260713 and concluded the tool could not defend against it — still true at the moment it happens, but it is now repairable afterwards. The app keeps the last 5 real upstream `ANTHROPIC_*` combinations (local addresses are never recorded), collected by the settings watcher and pinned once more right before each recording starts; Settings gets a dropdown plus a repair button, and `GET /api/settings/upstream-history` / `POST /api/settings/upstream-restore` expose the same thing to an agent. Restore aligns the whole `ANTHROPIC_*` namespace — token and model mapping come back together, and a provider that never had a `BASE_URL` key (official subscription) is repaired by *deleting* the keys rather than writing any URL. The entry whose credential matches the current one is preselected: that is the clean version of the very provider you are stuck on, so the repair really is one click. Tokens are redacted in the API and never leave the machine in cleartext.

- **The packaging configuration is reconciled too.** Two hard checks: **every source path in a spec's `datas` must exist**, and **the two specs may not diverge**. The first closes a hole this release actually walked into — when `AI_USAGE.md` moved into `docs/reference/`, the source paths inside both spec files were found by hand with grep, and missing one would have shipped a binary without its manual while `/api/ai-guide` **silently fell back** to a minimal cheat sheet that nobody would notice. The second guards against something that already happened: a comment in the spec records that the two files once diverged, with the macOS spec missing `brotli`, so macOS builds lost the body and usage of every non-streaming response — and the safety classifier is non-streaming. Differing platform backends are legitimate, so only the explicitly pinned parts are compared.

- **Three enumerations joined the reconciliation: `kind`, `err_kind`, and doctor rule codes.** The maintenance strategy had long designated an authoritative location for each, with nothing verifying that the values copied into the docs still matched. Documentation listing an enum value the code does not have now blocks the release — an agent would write handling for a branch that never fires, a human would go looking for a rule that does not exist. **The first attempt at the criterion was wrong in an instructive way**: one general "backticked items separated by slashes" rule to recognize enumerations produced 149 findings, every one a false positive, because field listings like `input` / `output` / `cache_read` have exactly that shape. These values are ordinary English words — `main`, `other`, `connect` — so **any extraction not anchored to context is guaranteed to misfire**. The two directions now use opposite criteria: ghosts are found through each enum's own anchor syntax (preferring misses), undocumented values through a wide match (does this word appear at all). One false positive survived that tightening, `aux`, which turned out to be a *lane* kind — a different enumeration that happens to share the name `kind`. The docs were right; the tool did not know about a fourth enum. Both wrong turns are now regression cases in `--self-test`.

- **The documentation audit became a gate instead of a report, and CI finally verifies anything at all.** `tools/doc_audit.py` used to exit 0 unconditionally, on a rationale written into the script: "lay out the evidence, report only differences — a difference is not an error, judgment is left to a human." That rationale holds for exactly half the differences. They are now split: **the documentation asserting something untrue of the code** (ghost endpoints, broken links, a stale `IDX_SCHEMA`, a self-test file that does not exist, a theme missing a token value) **blocks the release**, because a reader following it walks into a wall; **the code having something the docs omit** (unregistered internal endpoints and subcommands, dead tokens) only warns — the reader may fail to find it, but is never misled. Not drawing that line has a predictable ending: the first deliberately-undocumented internal endpoint stalls a release, someone appends `|| true` in CI, and **the gate is permanently dead while still posing as a defense**. `--json` obeys the exit code too (otherwise one flag bypasses the gate), and gained an `ok` field for agents. Alongside it, `release.yml` gained a `verify` job that `build` now depends on — **until now this workflow went from checkout straight to PyInstaller and then to publishing a release, with nothing in between; a tag whose self-tests had never run could ship**. Ten checks (syntax, four static reconciliations, six self-tests) now run before packaging. **The first CI run surfaced two problems that only a clean environment can show**: Windows runners default to pwsh, which does not expand globs like `src/*.py` (local Git Bash does, so local runs were always green), and — far worse — **Actions takes only the last command's exit code for a multi-line pwsh step**, so several failing reconciliations followed by one passing check would report success, silently disabling the gate in exactly the way it exists to prevent. The `verify` job is pinned to bash for that reason. The gate also caught a broken link to `src/_version.py`, which CI generates from the tag and the repo excludes, though a development machine has one — the docs were right and the audit was wrong to treat every mentioned path as a file that must exist, so `git check-ignore` now exempts generated files. The gate's own `--self-test` gained 8 classification assertions, 3 of them **inverted** (soft differences must *not* block) — a miscategorized gate would wave things through while printing "reconciliation passed", which is the exact shape of this project's repeat-offender bug ③.

### Changed

- **The BASE_URL warning banner carries a "Fix it" button straight to Settings.** The banner detected the loopback address but only said "check `~/.claude/settings.json`" — it left you to find the repair entry yourself (buried in Settings), and the banner's branch had no button at all. The button opens Settings directly; the wording now names the one-click repair and separates contamination/leftover (fixable) from an intentional local gateway such as vLLM (ignore). This closes the loop the previous entry also touched: detect → guide to the repair → banner clears on success.

- **`docs/` is now layered by rot risk and maintenance strategy instead of sitting flat.** Eight documents shared one directory while being fundamentally different things: `reference/` (architecture overview, dev guide, API contract, UI tour, AI_USAGE) describes the implementation precisely and goes stale the moment code changes; `methodology/` (problem-domain handbook, wire-format reader) is about *how to build this kind of observability tool* — it holds for a different harness and barely moves with this project's code. The root keeps the meta-document plus a new [`docs/README.md`](docs/README.md) index. Flattening them forced a single choice: either govern everything by the strictest rule or let the ones that matter slip through the loosest. **The real win of directories is that the reconciliation scope becomes a path rule rather than a maintained file list** — a new reference document lands in `reference/` and is covered automatically, whereas a list is exactly the thing people forget to update.
- **The single 1376px content cap is gone; width is now per-view.** On a fullscreen or ultrawide monitor every view sat in the same centered 1376px column with most of the screen empty on both sides — and the timeline DAG, a canvas of fixed-pitch lanes (300px each) with its own scroll, is exactly the view that suffers most: a busy day with a dozen-plus lanes could only be seen by scrolling horizontally or shrinking the graph with fit-width. The capture list now caps at 1760px (its summary column gets ~400px more text per row), and the timeline lifts the cap to `min(2560px, 100vw − 240px)` — wide enough that a 25-lane day fits whole at a comfortable zoom, but **not full-bleed**: the first version removed the cap entirely and edge-to-edge read as ugly, so the rule guarantees at least 120px of margin on any screen. Detail and settings views are unchanged, and so is everything below 1760px of window width.
- **The rot list in `文档维护策略.md` became a table of lessons instead of a chronicle (12KB → 4.8KB).** Its heading used to read `## 腐化清单（#1-12 260726 / #13-14 260729 / #15 260730 / #16-17 260802）` — **appended to four times, a date range stapled on each round** — in a meta-document about how to prevent documentation rot. Most of the dozen-plus itemized entries were already-fixed history; someone editing docs does not need to know that entry #1 was a missing endpoint fixed in some version, they need the **lesson** — and the lessons were already distilled in the notes below the table, coexisting with the details and drowned by them. What remains is four classified causes (copies always diverge / a remedy requiring manual sync is itself the next rot / numbers transcribed once will diverge / "some document mentions it" is not reconciliation), each with its most convincing instance; the itemized history goes back where it belongs, to `issues/` and the changelog. The document matrix, now duplicated by the new `docs/README.md`, is gone too. **The file itself said "this list has rotted before" — it knew, and answered by appending one more entry, which is the definition of patching over patching.**
- **`界面导览.md` drops the "reflections" that have already been addressed (20KB → 18.8KB).** Each view in that document carries a fixed structure (what you see / where the data comes from / reflection / traps), where the reflection covers what's currently wrong with the UI — but two of them described problems **fixed long ago** (collapsed response headers, three dead config toggles), and one duplicated §2.4 sentence by sentence, down to the same quoted code comment and field list. The reflections that remain all point at real present-day limits. A dozen-odd "as of v0.4.0 this does X" / "changed on 260801" annotations went with them — **someone reading about the UI only needs to know what the UI does now**; the change history is the changelog's job. A few stay: that subagent lane keys are the official CC instance ID for new recordings while pre-07-31 recordings still carry a meaningless hash, for instance, explains why an older recording on the reader's disk looks different.
- **Two documents whose names misdescribed them were renamed.** `开发指南.md` ("dev guide") → **`开发约定.md`** ("dev conventions"): its content is what you must not break when changing code — safety invariants, repeat-offender bugs, the self-test list — while "guide" promises onboarding and how-to, which is exactly `CONTRIBUTING.md`'s job. The two collided in the reader's head. The file's own opening line already called it "the single source of truth for this project's development conventions"; the name now matches. `问题域手册.md` ("problem-domain handbook") → **`同类工具构建手册.md`** ("building a tool of this kind"): "problem domain" is too abstract to tell a reader whether to open it, and the content is about which classes of problem you must solve to build a comparable observability tool on another harness. **`AI_USAGE.md` deliberately keeps its English name** — it ships inside the binary to users worldwide and its primary reader is an agent, so an all-Chinese filename would raise the barrier rather than lower it. That is an audience judgment, not a cost compromise.
- **`架构总览.md` is back to answering only "how the modules are layered".** It had grown to 44KB with three sections at the end that belonged elsewhere: the evolution narrative (overlapping CHANGELOG and release tags), four design principles (a second telling of the dev guide — one of them literally annotated as "a direct restatement of repeat-offender bug ④"), and a prose summary of the codebase's temperament. **One of them had already started saying something false**: the evolution section closed with "what remains is cross-day trends", which shipped back in v0.4.6 — narrative growing on the end of a reference manual rots on its own schedule. Each of the four principles was checked against its home in the dev guide before deletion; nothing was lost. The document now opens with a boundary clause as a guardrail: it covers module layering and data flow only, while history, code-change rules, and design trade-offs each have their own home — **ask which of those three a new addition is before adding it here**.

### Fixed

- **The prompt board's "swap sides" button threw instead of swapping.** It called the board renderer with no argument after the renderer had gained a `which` parameter (one board per sub-page), so it dereferenced an undefined config and died on a `TypeError` — the two snapshots swapped in memory, the board never redrew, and the diff below re-rendered identically because it reads the same two ids in the same order. Introduced in the same round that split the boards; caught by reading the call sites rather than by any test, since neither `node --check` nor the reference audit can see an arity mismatch.

- **One-click repair now clears the top BASE_URL banner, and the doctor's stuck-config advice no longer dead-ends.** Two loose ends in the upstream-history repair shipped above. The red BASE_URL banner is driven by a module-level cache (`_base_url_warning`) that refreshed only when the proxy started; the repair endpoint rewrites `settings.json` through a different path and never touched that cache, so the banner stayed lit after a successful repair — the in-page notice cleared (it re-reads the file each time), but the top banner kept showing the pre-repair loopback address until you restarted the app. The cache is now reconciled on every repair (`resolve_base_url_warning`). Separately, the doctor's `self_reference_state` and `dead_port_leftover` rules advised "stop, then start again" / "start the proxy" — but starting the proxy when BASE_URL points at the tool's own port is refused by the self-reference guard, so the advice walked into a wall in exactly the cc-switch-contamination case the repair feature exists to fix. Both now direct you to Settings → Upstream config history → Fix it.

- **Two silent-failure points in the documentation audit itself, exposed by that reorganization.** `doc_audit` used `glob("*.md")`, which only sees the top level of `docs/` — move documents into subdirectories and the whole batch drops out of reconciliation while the script still prints "all clean". It also hard-coded a read of `docs/reference/开发约定.md` to extract the self-test list, and `_read()` returns an empty string for a file it cannot open, so "the document moved" masquerades as "the document has no problems". The first is now `rglob`; the second goes through a new `_read_required()` that exits with an error naming the path constant to fix. **An audit tool that reports its own blindness as a pass is worse than no audit**, because it also hands you false confidence.
- **`serve` no longer exits when it cannot patch settings.json.** It used to `sys.exit(1)`, which created a dead end precisely for the failure above: a local self-referencing BASE_URL makes the snapshot guard refuse to patch, and the endpoint that repairs it lives *inside that very process*. The service now starts anyway (just not recording), and logs the three commands that get you out.
- **The proxy's auto-start in `serve` mode was a copy of the `/api/proxy/start` logic, not the same logic.** Its comment claimed they were identical while the new history collection had only been added to the route — so `serve` never recorded any history. Both now call `app.begin_recording()`.
- **Settings no longer contradicts itself about the current BASE_URL.** That row reads the in-memory snapshot ("what stopping the proxy would restore"), so during this failure it showed the last known real upstream while the warning right below it said `127.0.0.1` — and it showed `—` outright when the proxy had never successfully started. It now falls back to the on-disk value whenever recording is not active.
- **Non-UTF-8 characters in upstream error messages are no longer destroyed on the way in.** Error bodies were decoded as UTF-8 unconditionally (`errors="replace"`), so a gateway answering in GBK turned every illegal byte into `�` **at the moment of writing** — not a display problem: read the index file as binary and the replacement characters are what is stored, with nothing left to recover. That lands squarely on this project's central claim — "a failed upstream response is not noise, it is a problem report the upstream has already diagnosed once" — because a problem report you cannot read voids that claim for every non-UTF-8 upstream. The charset declared in `Content-Type` is now honored; with no declaration, UTF-8 is tried **strictly** first, then GBK, and finally latin-1 as a floor (**it never fails and loses no bytes** — the original bytes can still be recovered from the text, which is the exact opposite of `errors="replace"`). Every fallback is recorded and surfaced in the UI. The order cannot be reversed: GBK decodes a great many UTF-8 byte sequences "successfully", just into garbage. **The two in-protocol decodes were deliberately left alone** — SSE and JSON bodies follow the Anthropic protocol, which mandates UTF-8; the error body comes from the gateway itself and is bound by no such protocol. This is the second layer of one disease: `_decode_body` has always handled content-**encoding** (compression) and nobody ever handled **charset**.
- **One burst of rate limiting no longer shatters into 16 groups.** The failure-fingerprint normalizer knew two identifier shapes, a `req_*` prefix and a canonical UUID, while this gateway's request id is a 30-character undelimited hex string (`20260802082259ad76…`) — neither matches, and even the catch-all "4+ digit number" rule cannot reach it, because there is no word boundary between a digit and a letter. So a single two-minute burst on 2026-08-02 became 16 separate groups of `count=1`. That is more than untidy: CLI output is bounded (20 groups by default), so **the fragments push genuine cross-day patterns out of view** — the more errors there are, the finer they shatter, and the aggregation fails exactly when it is needed most. Long hex identifiers are now normalized, with a 16-character threshold (shorter hex may be a meaningful error code — a reverse assertion in the self-test guards that line).
- **The four static-reconciliation scripts in `tools/` no longer fail spuriously on a default Windows console.** They lacked the `sys.stdout.reconfigure(encoding="utf-8")` that `src/` self-tests have always had: a GBK console cannot encode `✓`, so `check_render` **passed every check and then crashed on its own `[ALL PASSED]` line, exiting non-zero** — a guard that reports "all passed" as "failed" is worse than no guard. The other three only printed Chinese so they did not crash, but their output was mojibake and unreadable to humans and agents alike.

## v0.4.9 - 2026-08-03 (hotfix)

### Fixed

- **The aux aggregate card's per-kind counts are visible again.** v0.4.8's aggregate card reused the plain node height (62px) for a three-row layout (time row / meta row / per-kind badge row ≈ 72px); the card is a flex column with `overflow:hidden`, so the badge row was first squeezed by `flex-shrink` and then clipped to a 10px sliver — the per-kind counts (title / security / count_tokens) were in the DOM and the tooltip but visually unreadable ("the counts are gone"). The card gets its own height constant (`NH_AGG` = 76); `dagPlace` is shared by full and incremental renders, so both paths pick it up. Worth noting for the next fixed-height card: flex squeezes the last row *inside* the box before `overflow` clips it, so `scrollHeight == clientHeight` — a pure overflow check cannot see this; you have to measure the last row's own height.
- **CLI `errors` now returns `ok: true`** like the other ten subcommands. It was the only one without the top-level flag, so an agent checking `data["ok"]` got `undefined`.

### Added

- **`tools/check_render.py` — a static audit that a fixed-height card's content rows fit its height constant.** The root cause shared by both recent visual bugs (v0.4.7 hiding the aux lane, v0.4.8 clipping the aggregate card) is that the six selftests are all backend data-layer e2e — front-end visual completeness had zero automated cover. The project has no browser automation (single-exe, no playwright), so runtime DOM overflow scans can't be automated; instead this maintains a `card → rows → padding → height-constant` table and asserts `rows × 18 + padding ≤ constant`, with the constants parsed live from `const DGX={}` so changing one needs no script edit. It catches the v0.4.8 shape (NH_AGG=62 would report 70 > 62); `--self-test` mutates NH_AGG to 62 to prove the check actually fires. Added to the dev guide's static-reconciliation list alongside `check_i18n_js` and `doc_audit`.

## v0.4.8 - 2026-08-02 (hotfix)

### Fixed

- **The aux lane is back in the folded timeline — one aggregate card per session.** v0.4.7's turn fold hid every attributed auxiliary call into turn-card badges; on a day where all aux had an owning turn (124/124 on 08-02), the aux lane vanished outright, and every near edge degenerated into a self-loop hidden behind its turn card — "which session did this security audit belong to" ceased to be visible unless you already knew which turn to expand. Now each main lane's auxiliaries fold into a single aggregate card in the aux lane: lane-coloured border and count chip, per-kind badges, placed at its first member's time slot, with near edges converging from the turn cards onto it. Clicking expands that session's auxiliaries in place; expanding a turn pulls that turn's own auxiliaries out as individual cards and the aggregate's count shrinks accordingly. Unattributed auxiliaries still show individually — folding those away would be silent data loss. Measured on 08-02: 192 nodes → 71 cards (68 turn cards + 3 aggregate cards), versus 68 with the lane gone.

## v0.4.7 - 2026-08-02

### Added

- **The timeline folds by conversation turn instead of hiding tool calls.** What survived the old filter were still *requests*, while the thing you actually search by is what you said. Now it is one card per turn: your message as the body, badges for the subagents that turn spawned and counts for the auxiliary calls it triggered; click to expand the individual requests (measured: 19 lanes / 192 nodes down to 18 lanes / 68 cards on a real day). A card only goes red when *every* request in the turn failed — 29 of 68 turns on that day contain at least one failure, and tinting them all would waste the colour. Adds `turn_user` to the index (`IDX_SCHEMA` 14→15), which **must** be computed at write time: `last_user` is capped at 2000 chars while CC's injected reminders reach 9960.
- **Three interface themes, dark by default.** Dark Professional / Classic Warm (identical to v0.4.6) / Lab Daylight, switching instantly. The choice lives in a cookie plus localStorage and **never reaches the backend `config.json`** — that file is the source of truth for proxy behaviour. The same pass fixed toast and status-chip contrast, keyboard activation, ARIA semantics, reduced motion, and narrow and high-zoom layouts. Lane palettes are per-theme: one set of six colours cannot sit on charcoal and on paper and pass AA on both.
- **Blind-spot radar `/api/unknowns` — every value outside the known sets, in one call.** Previously "unknowns" could only be found by a human scanning jsonl. `index_record` computes an `unknowns` block per record (block types and fields, request fields, stop_reason, thinking.type), and the endpoint aggregates each dimension into `{value, count, samples, content snippet, hosts, cc_versions}`. The first run over 12 days and 5414 records surfaced six classes, including `tool_use.caller` (464 records, never parsed at all) and `thinking.type=adaptive` (3206, a non-standard enum value).
- **Cross-day failure trends `/api/diagnose/trends`.** The single-day view cannot answer "new or recurring, and concentrated on which vendor or CC version?". Groups merge across days on the same fingerprint, giving per-day curves, a trend tag, and by_host / by_model / by_cc_version slices. **HTTP and CLI only, no GUI** — the cross-day dimension explosion is an agent's sweet spot and a human's nightmare.
- **`/api/grep` and `/api/stats` HTTP endpoints.** Previously CLI-only, so an agent that wanted to search content had to read the jsonl directly — exactly what ai-guide rule ① forbids. The logic moved into `capture_store` as a single source shared by CLI and HTTP: `stats` losing `cache_creation` (~38% of the cost) happened because the two sides each had their own copy.
- **`unknowns` and `trends` on the CLI; every read-only surface takes a session filter.** The self-audit workflow has to be CLI-first for a concrete reason: `serve` patches your real `settings.json` (that is how recording works) while auditing is supposed to be read-only. "What unknowns piled up this week" should not require the one action in the project that has side effects.
- **`tools/doc_audit.py` — machine reconciliation of code facts against documentation claims.** It checks six mechanically decidable things: endpoints present in `API契约.md` (the designated source — "some doc mentions it" doesn't count), CLI subcommands documented, doc-referenced paths that exist, the `IDX_SCHEMA` value asserted in prose, the self-test list, and references to endpoints that no longer exist. Reports differences, never verdicts, always exits 0. The first run found four.
- **Two new kinds, `quota_probe` and `hook_eval`; `other` drops to zero.** The 10 records that fell through to `other` turned out to be two stable shapes: CC's quota probe and StopConditions hook evaluation.
- **`host` and `cc_version` in the index (`IDX_SCHEMA` 12→13).** `host` is the wire-level fact about **which vendor served the request** — the same `claude-opus-5` may go to the official endpoint, a gateway or an aggregator, and the model name cannot tell you which.
- **Auto fit-width no longer shrinks below 50%.** On the 19-lane day it computed 21%, where no text on any card is readable — "fit width" was a promise it could not keep.

### Changed

- **Radar: three corrections to what it was actually pointing at** (found by re-checking 5505 real records over 12 days). (1) Each unknown now carries `hosts` / `cc_versions`: on the day re-checked, **all five unknowns came from one third-party gateway**, while the endpoint's note said "protocol evolution — fold the stable ones into `KNOWN_*`". Doing that would widen the criteria for the official link based on one gateway's shape, and the radar would go quiet the day the official endpoint really does emit a same-named different block. (2) `betas` is now scored by lift (`P(beta|records with this unknown) ÷ P(beta|all)`, kept at ≥1.5) instead of raw counts: raw counts always report whichever flags every request carries, and for an unknown seen once every beta ties, degrading `most_common` into "the first few in the header". **An empty list is now the honest answer.** (3) This tool's own degradation markers (`_input_raw` and friends) are reported as a separate `degraded` dimension rather than as protocol evolution.
- **Trends: `burst`, staleness, and no more junk-drawer group.** A 2650-failure single-day incident used to be tagged `sporadic` (the old definition only asked whether a group appeared on one day); a group that stopped two weeks ago still read as `recurring` (shape and freshness are two things — now separated into `days_since_last` / `stale`); and every vendor's opaque `Error` or `timeout` merged into one cross-vendor junk drawer (now split by host).
- **Radar known-set coverage**: the `compaction` block — **assembled by this tool's own SSE accumulator** — was neither in the known sets nor handled by any renderer. We did not recognise a block we build ourselves.
- **`stats` reads the index.** It used to parse the main file line by line and call `classify(full record)` on each one, re-running the whole of `index_record` — including matching against the ~108K security ruleset — for every record.
- **`/api/dag` results are cached by date plus recording-file size**; list rows show a session short code when a day holds more than one session (silent otherwise), and `/api/captures` summaries carry `session_id`.
- **`server_tool_use` blocks get their own renderer** (previously a raw JSON dump that hid what was called); **`output_config.format` is indexed**; and **startup warns when `BASE_URL` is already a local address** (leftover, profile contamination or a manual edit — a non-proxy port is not refused, since it may be a legitimate local gateway).

### Documentation

- **A documentation pass driven by reconciliation rather than by feel**: `API契约.md` gained the grep / stats sections it never had plus a radar field table, `AI_USAGE.md` gained the full 17-row CLI table and the session filter, `开发指南.md` had its radar section rewritten and the three-theme frontend conventions added, and `问题域手册.md` gained unit 10, which writes the radar up as a portable method.
- **All twelve README screenshots (4 views × 3 languages) were retaken**: the default look changed, and the front page should not advertise the old one. Generated from `dev_seed`'s synthetic captures — screenshots go into a public repository and must not carry real recorded traffic.

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
