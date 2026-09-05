# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md). One line per change here; the reasoning, evidence and rejected alternatives live in the git commits and in the local `issues/` records.

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand exposing a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed.
- **Current status**: **v0.4.26 (2026-09-05)** — the detail view finally shows what CC asked for: the whole call-parameter block, with fields we have never seen highlighted.
- **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. Turn a recurring failure pattern into a check automatically — `/api/diagnose/trends` answers "new or recurring?", but writing the rule is still manual.
  2. Decide whether turn origin should ever be corrected at runtime from Claude Code's local logs. It currently is not, and that restraint is the point — the app's data surface is the traffic it recorded plus one settings field.
  3. Storage follow-ups, both measured and deliberately deferred: delta-encode the skeleton's pointer lists (est. 477 MB → ~10 MB), and let retention compact before it deletes.

## v0.4.26 - 2026-09-05

### Added

- Detail view shows the whole call-parameter block from the request body; unseen fields are highlighted.

## v0.4.25 - 2026-09-04

### Fixed

- `doc_audit` now limits blockquotes in `docs/` to warnings, self-check hooks and each file's audience header; 69 rhetorical ones became plain text.
- `doc_audit` now caps CHANGELOG entries (25 words / 40 characters) and rejects hard-wrapped lines; the entries above were trimmed to fit.
- Docs: the build-your-own handbook moved to `handbook/`, the wire-format reference into `docs/reference/`, and `doc_audit` now checks that relative links resolve.
- `doc_audit` now reconciles endpoint headings too: one section per (method, path), and declared methods, query parameters and `error_code` values must exist.
- A prompt the upstream refuses and Claude Code re-sends now merges into the turn it retries, badged "retried xN", instead of opening its own turn.
- Reasoning availability is judged by plaintext, not block presence: signature-only recordings drop to tier C (`signature_only`); new `steps_with_plaintext` field.
- API contract: the duplicated analysis endpoint is gone and the catch-all chapter was split three ways; six docs lost essay openings and heading date stamps.

## Earlier versions

v0.4.22 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
