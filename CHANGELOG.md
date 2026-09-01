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
- **Current status**: **v0.4.21 (2026-08-31)** — today's recording compacts as it goes instead of
  waiting for the next day, and the analysis the app has already computed is now exposed to external
  agents. Unreleased since: request classification and turn boundaries now follow bits Claude Code
  declares itself.
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

## Unreleased

### Fixed

- Session-naming requests (title, kebab-case slug) are classified as auxiliary again, not main line.
  Claude Code 2.1.238 rewrote the prompt and every wording fingerprint missed it; the classifier now
  reads `output_config.format.type`, which Claude Code declares itself (26/26 hit, 0 false positives
  across 3,349 main-line requests).
- A dialog-shaped request that carries no tool list is no longer classified as main line.
- Text that a tool returned alongside its result — an image note, fetched page content, an interrupt
  marker — no longer starts a new turn. One recorded day went from 17 turns to 9; measured against
  Claude Code's own `promptId`, turn counts went from +70% to +56% over truth.
- The turn-boundary rule had three separate implementations that disagreed, so the timeline view and
  the analysis view reported different turn numbers. They now share one.
- `tools/origin_probe.py` read raw `{date}.jsonl` only, so it silently covered nothing once
  recordings were compacted into `.pack` (7 of 8 local days).

### Added

- Blind-spot radar reports a `mainline_suspect` dimension: requests classified as main line that
  lack the structural marks of one. Computed at aggregation time, so no index rebuild is needed.
- `tools/origin_probe.py` gained three reconciliation modes (`--mode belong | turns | origin`).

### Other

- `IDX_SCHEMA` 15 → 16 (turn-boundary semantics changed; indexes rebuild themselves).

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

## Earlier versions

v0.4.20 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the
[GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the
same notes per version.
