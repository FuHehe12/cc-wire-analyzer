# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md).
> One line per change here; the reasoning, evidence and rejected alternatives live in the
> git commits and in the local `issues/` records.

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key
> decisions that are rules or invariants live in the local CLAUDE.md (developer conventions).
> Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic
  between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs
  and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand exposing a
  headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships
  inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed.
- **Current status**: **v0.4.22 (2026-09-01)** — request classification, turn boundaries and
  security-review parsing now follow the bits and formats Claude Code declares itself.
- **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed
  `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced,
  delete it yourself.
- **Next steps**:
  1. Turn a recurring failure pattern into a check automatically — `/api/diagnose/trends` answers
     "new or recurring?", but writing the rule is still manual.
  2. Decide whether retry storms should be merged or kept visible (one day: 2,049 "turns", 2,000 of
     them 504 retries of three real questions).
  3. Decide whether turn origin should ever be corrected at runtime from Claude Code's local logs.
     It currently is not, and that restraint is the point — the app's data surface is the traffic it
     recorded plus one settings field.
  4. Storage follow-ups, both measured and deliberately deferred: delta-encode the skeleton's
     pointer lists (est. 477 MB → ~10 MB), and let retention compact before it deletes.

## v0.4.22 - 2026-09-01

### Fixed

- Session-naming requests (title, kebab-case slug) are classified as auxiliary again, not main line.
- Dialog-shaped requests that carry no tool list are no longer classified as main line.
- Text a tool returns alongside its result — image notes, fetched page content, interrupt markers — no longer starts a new turn.
- Turn boundaries had three inconsistent implementations; the timeline and analysis views now share one.
- Security reviews recorded from Claude Code 2.1.238 onward show the right action under review again, and an honest count of prior actions.
- Security nodes in the timeline now show the verdict, not only the action under review.
- `tools/origin_probe.py` covered nothing once a day had been compacted into a `.pack`.

### Added

- Blind-spot radar gained a `mainline_suspect` dimension: requests classified as main line that lack main-line structure.
- `tools/origin_probe.py` gained three reconciliation modes (`--mode belong | turns | origin`).

### Other

- `IDX_SCHEMA` 15 → 17; the index rebuilds itself.

## Earlier versions

v0.4.21 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the
[GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the
same notes per version.
