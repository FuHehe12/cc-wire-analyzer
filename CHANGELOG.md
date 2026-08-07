# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md).

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed to use it from an agent.
- **Current status**: **v0.4.9 released** (2026-08-03, hotfix); unreleased on top of it: upstream config history with one-click repair, which finally answers a failure the docs had written off as undefendable — a switcher tool freezing the proxy's local address into a provider, so that switching *back* to it later leaves Claude Code pointed at a dead local port. v0.4.8's aux aggregate card reused the plain node height (62px) and clipped its per-kind count badges to a sliver — the title/security/count_tokens counts were in the DOM but visually unreadable; the card now has its own height constant (`NH_AGG`=76). The two recent visual bugs are now both settled: the fold that hid the aux lane outright (v0.4.7) and the card that brought it back but clipped its counts (v0.4.8). A static audit (`tools/check_render.py`) now guards every fixed-height card against this overflow shape, and the root cause — six selftests all backend e2e, zero front-end visual cover — is documented in the dev guide's repeat-offender list. **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. **Close the self-improvement loop.** `/api/diagnose/trends` now answers "new or recurring?" reliably, but turning a recurring pattern into a check is still manual — `effort_max_rejected_upstream` exists because a human noticed a recurring failure and wrote a rule for it. Automating that half is what makes the radar and the trends more than a reading exercise.
  2. **Identity residual** (deferred): interactive-mode (`cc_entrypoint=cli`) subagents still lack a hand-verified capture. Historical captures supply statistical evidence (225 requests, all carrying the flag, no counterexample), but that is not the same as a session captured and checked against ground truth.
  3. The recording-blind-spot audit (protocol side and capability side) closed across v0.4.3–v0.4.6; method in `docs/开发指南.md` §2.5 and unit 0 of `docs/问题域手册.md`.

## Unreleased

### Added

- **Upstream config history, and one-click repair when a switcher tool freezes the proxy's local address into a provider.** The failure is a delayed one, which is why it was so hard to place: while recording, `ANTHROPIC_BASE_URL` points at `http://127.0.0.1:<port>`; if you switch providers at that moment, the switcher saves the *current* settings.json — local address and all — into the provider you are leaving. Nothing breaks then. It breaks whenever you switch *back*: Claude Code is now pointed at a local port nobody is listening on, and third-party tokens and the official subscription fail alike, while the config still *looks* fine. `docs/AI_USAGE.md` has warned about this since 260713 and concluded the tool could not defend against it — still true at the moment it happens, but it is now repairable afterwards. The app keeps the last 5 real upstream `ANTHROPIC_*` combinations (local addresses are never recorded), collected by the settings watcher and pinned once more right before each recording starts; Settings gets a dropdown plus a repair button, and `GET /api/settings/upstream-history` / `POST /api/settings/upstream-restore` expose the same thing to an agent. Restore aligns the whole `ANTHROPIC_*` namespace — token and model mapping come back together, and a provider that never had a `BASE_URL` key (official subscription) is repaired by *deleting* the keys rather than writing any URL. The entry whose credential matches the current one is preselected: that is the clean version of the very provider you are stuck on, so the repair really is one click. Tokens are redacted in the API and never leave the machine in cleartext.

### Fixed

- **`serve` no longer exits when it cannot patch settings.json.** It used to `sys.exit(1)`, which created a dead end precisely for the failure above: a local self-referencing BASE_URL makes the snapshot guard refuse to patch, and the endpoint that repairs it lives *inside that very process*. The service now starts anyway (just not recording), and logs the three commands that get you out.
- **The proxy's auto-start in `serve` mode was a copy of the `/api/proxy/start` logic, not the same logic.** Its comment claimed they were identical while the new history collection had only been added to the route — so `serve` never recorded any history. Both now call `app.begin_recording()`.
- **Settings no longer contradicts itself about the current BASE_URL.** That row reads the in-memory snapshot ("what stopping the proxy would restore"), so during this failure it showed the last known real upstream while the warning right below it said `127.0.0.1` — and it showed `—` outright when the proxy had never successfully started. It now falls back to the on-disk value whenever recording is not active.

## v0.4.9 - 2026-08-03 (hotfix)

### Fixed

- **The aux aggregate card's per-kind counts are visible again.** v0.4.8's aggregate card reused the plain node height (62px) for a three-row layout (time row / meta row / per-kind badge row ≈ 72px); the card is a flex column with `overflow:hidden`, so the badge row was first squeezed by `flex-shrink` and then clipped to a 10px sliver — the per-kind counts (title / security / count_tokens) were in the DOM and the tooltip but visually unreadable ("the counts are gone"). The card gets its own height constant (`NH_AGG` = 76); `dagPlace` is shared by full and incremental renders, so both paths pick it up. Worth noting for the next fixed-height card: flex squeezes the last row *inside* the box before `overflow` clips it, so `scrollHeight == clientHeight` — a pure overflow check cannot see this; you have to measure the last row's own height.
- **CLI `errors` now returns `ok: true`** like the other ten subcommands. It was the only one without the top-level flag, so an agent checking `data["ok"]` got `undefined`.

### Added

- **`tools/check_render.py` — a static audit that a fixed-height card's content rows fit its height constant.** The root cause shared by both recent visual bugs (v0.4.7 hiding the aux lane, v0.4.8 clipping the aggregate card) is that the six selftests are all backend data-layer e2e — front-end visual completeness had zero automated cover. The project has no browser automation (single-exe, no playwright), so runtime DOM overflow scans can't be automated; instead this maintains a `card → rows → padding → height-constant` table and asserts `rows × 18 + padding ≤ constant`, with the constants parsed live from `const DGX={}` so changing one needs no script edit. It catches the v0.4.8 shape (NH_AGG=62 would report 70 > 62); `--self-test` mutates NH_AGG to 62 to prove the check actually fires. Added to the dev guide's static-reconciliation list alongside `check_i18n_js` and `doc_audit`.

## Earlier versions

v0.4.8 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
