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
- **Current status**: **v0.4.24 (2026-09-02)** — security reviews of a sub-agent's tool calls are
  attributed to that sub-agent on the timeline; fold-mode switching and edge drawing are clean;
  the Windows index-rebuild bug is fixed.
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

- Docs, batch 3 (audience): the handbook on building a tool like this one moved out of `docs/` to
  `handbook/` at the repository root and is now linked from all three READMEs - its readers are
  people wiring up an analyser for another agent harness, and it should not be maintained as part of
  this project's manual. `报文解读.md` moved the other way, into `docs/reference/`: it had been
  filed as "low corruption, not reconciled" while in fact it tracks the kind enum and has always
  been part of that reconciliation - the move caught the proof, a cross-reference still promising
  "9 kinds" when there have been 11 for a while. `doc_audit` also now checks that relative markdown
  links resolve (179 of them, one was broken by this very move).
- Docs, batch 2 (the reconciliation gate now reads endpoint headings): `doc_audit` used to check
  only that a path exists somewhere in the contract - writing the same endpoint twice satisfied
  that, which is how batch 1's diverged duplicate grew. It now also checks that each (method, path)
  owns exactly one section, that every method and query parameter a heading declares exists in the
  code, and that documented `error_code` values are real. Switching it on caught a real one: the
  contract advertised `POST /api/snapshots/<id>/semantic`, but that path is GET-only - the pipeline
  it described lives on `POST /api/snapshots/<id>/trajectory`. Both sections are corrected.
- A prompt the upstream refuses is re-sent verbatim by Claude Code, and every re-send used to open
  its own turn on the timeline — one measured lane had ten turns carrying the same sentence, all
  inside one minute. Re-sends now merge into the turn they are retrying (same text, previous attempt
  errored, within 60s), carrying a "retried xN" badge and the reason on hover. Nothing is hidden:
  every request stays a step inside that turn, so expanding it shows each attempt. Measured on one
  day: 99 turns became 80, against Claude Code's own count of 81.
- Reasoning availability is now judged by plaintext, not by block presence. A recording whose
  thinking blocks all came back signature-only (measured on claude-opus-5: 86 blocks, zero
  characters) used to be tier A, so the agent brief sent the reader off to "read the reasoning" and
  the drawer was empty. Those recordings are tier C with reason `signature_only`, and tier C now
  gets the behaviour chain and the do-not-speculate guard that only tier B used to get. New
  `steps_with_plaintext` field alongside `steps_with_thinking` (blocks); a tier-A recording that
  still hides empty blocks is flagged `partial_empty`.
- Docs, batch 1 (divergences and style): the API contract's stale duplicate of
  `GET|POST /api/snapshots/<id>/analysis` is gone, and its catch-all chapter was split — LLM
  endpoints stay, snapshot export/import moved to the snapshots chapter, and a new "Instance &
  environment" chapter now holds about/storage/instance(s)/ai-guide/open-folder. The three docs
  still carrying essay-style openings/closings lost them, numbered headings were de-numbered, date
  stamps were moved out of every heading across six docs (32 spots), and one link to a
  repo-excluded local file was made self-contained. `doc_audit` reconciles clean; every endpoint is
  documented exactly once.

## v0.4.24 - 2026-09-02

### Fixed

- Security reviews of a sub-agent's tool calls are now attributed to that sub-agent on the timeline
  instead of the mainline. Turn cards, cascade hiding and token costs follow the corrected owner;
  no other auxiliary kind is affected.
- On Windows, index rebuilds after a schema bump used to append to the old file instead of replacing
  it, so index files kept growing; they are now replaced, and already-bloated files clean themselves
  up on first read.
- Timeline: a folded card standing in for many nodes no longer draws dozens of identical overlapping
  edges; the aux lane no longer chains calls from different sessions into one "conversation order"
  line; switching the fold mode now resets expanded aux aggregate cards too.
- Reference docs: all five audited end to end — contradictions fixed, essay-style openings and
  closings dropped, patched-in section numbers renumbered (the agent manual shipped in the binary
  included).

## Earlier versions

v0.4.22 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the
[GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the
same notes per version.
