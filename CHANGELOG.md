# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md).

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed to use it from an agent.
- **Current status**: **v0.4.8 released** (2026-08-02, hotfix). The folded timeline's aux lane is back — v0.4.7's turn fold had hidden every attributed auxiliary call into turn-card badges, and on a day where all aux had an owner (124/124 on 08-02) the lane vanished outright and its near edges collapsed into self-loops; each session's auxiliaries now fold into one lane-coloured aggregate card in the aux lane (click to expand), instead of disappearing. The turn fold itself stays — what the day's data corrected is *folding aux per session*, not *hiding it*. For what v0.4.7 added (turn cards, three themes, radar/trends re-check, doc reconciliation), see its entry below. **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. **Close the self-improvement loop.** `/api/diagnose/trends` now answers "new or recurring?" reliably, but turning a recurring pattern into a check is still manual — `effort_max_rejected_upstream` exists because a human noticed a recurring failure and wrote a rule for it. Automating that half is what makes the radar and the trends more than a reading exercise.
  2. **Identity residual** (deferred): interactive-mode (`cc_entrypoint=cli`) subagents still lack a hand-verified capture. Historical captures supply statistical evidence (225 requests, all carrying the flag, no counterexample), but that is not the same as a session captured and checked against ground truth.
  3. The recording-blind-spot audit (protocol side and capability side) closed across v0.4.3–v0.4.6; method in `docs/开发指南.md` §2.5 and unit 0 of `docs/问题域手册.md`.

## v0.4.8 - 2026-08-02 (hotfix)

### Fixed

- **The aux lane is back in the folded timeline — one aggregate card per session.** v0.4.7's turn fold hid every attributed auxiliary call into turn-card badges; on a day where all aux had an owning turn (124/124 on 08-02), the aux lane vanished outright, and every near edge degenerated into a self-loop hidden behind its turn card — "which session did this security audit belong to" ceased to be visible unless you already knew which turn to expand. Now each main lane's auxiliaries fold into a single aggregate card in the aux lane: lane-coloured border and count chip, per-kind badges, placed at its first member's time slot, with near edges converging from the turn cards onto it. Clicking expands that session's auxiliaries in place; expanding a turn pulls that turn's own auxiliaries out as individual cards and the aggregate's count shrinks accordingly. Unattributed auxiliaries still show individually — folding those away would be silent data loss. Measured on 08-02: 192 nodes → 71 cards (68 turn cards + 3 aggregate cards), versus 68 with the lane gone.

## Earlier versions

v0.4.7 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
