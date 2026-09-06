# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md). One line per change here; the reasoning, evidence and rejected alternatives live in the git commits and in the local `issues/` records.

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand exposing a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed.
- **Current status**: **v0.4.27 (2026-09-06)** — updated non-secret defaults, unified online documentation, and a redesigned bilingual website.
- **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. Turn a recurring failure pattern into a check automatically — `/api/diagnose/trends` answers "new or recurring?", but writing the rule is still manual.
  2. Decide whether turn origin should ever be corrected at runtime from Claude Code's local logs. It currently is not, and that restraint is the point — the app's data surface is the traffic it recorded plus one settings field.
  3. Storage follow-ups, both measured and deliberately deferred: delta-encode the skeleton's pointer lists (est. 477 MB → ~10 MB), and let retention compact before it deletes.

## Unreleased

- Development conventions and API contracts return to `docs/reference/*.md`; the manual is generated from them.
- The manual now bundles five reference documents; doc links point at the online manual and stay readable on GitHub.
- `doc_audit` gains a body-length gate: a named document reduced to a redirect page now fails.
- The Chinese changelog catches up with v0.4.27.

## v0.4.27 - 2026-09-06

- Default settings enable rolling compaction and prefill DeepSeek, with larger analysis limits; API keys remain empty.
- The website explains prompts, run timelines, snapshots, translation and AI explanations, with online documentation and expandable screenshots.
- Documentation maintenance rules join the product manual; research findings and remaining design questions replace duplicate historical notes.
- API contracts and development conventions now live in the product manual; compatibility links and documentation checks remain intact.

## Earlier versions

v0.4.26 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
