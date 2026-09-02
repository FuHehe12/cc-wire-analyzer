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
- **Current status**: **v0.4.23 (2026-09-02)** — the turns Claude Code starts by itself no longer
  count as mainline; turn counts now line up with Claude Code's own conversation log.
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

- Security reviews of a sub-agent's tool calls are now attributed to that sub-agent instead of the
  mainline. Claude Code hides this on the wire — every side query is stamped as the main agent — but
  it puts the reviewed agent's own conversation in the request body, so the sub-agent is identifiable
  from the same anchor already used for sub-agent lanes. Across 7 days: 28 of 556 security reviews
  belong to a sub-agent (40% on days with heavy sub-agent use), and no other auxiliary kind ever
  does. Turn cards, cascade hiding and token costs follow the corrected owner.
- Index rebuilds after a schema bump now actually replace the old index file on Windows instead of
  appending to it. The old file could not be deleted while the same process still held it open for
  reading, so every read re-appended a whole day: one local day had 196 records stored as 3,955 index
  lines across four schema generations. Reads always returned correct data, which is why it went
  unnoticed. The bloated files are cleaned up on first read.
- Reference docs: audited all five end to end, fixed what they contradicted about themselves and
  about each other, dropped the essay-style openings and closings, and renumbered the patched-in
  section numbers into a straight sequence. The agent manual shipped in the binary (`--help`,
  `GET /api/ai-guide`) is one of them.
- The timeline no longer draws dozens of identical overlapping edges when a folded card stands in
  for many nodes, and the auxiliary lane no longer draws a "conversation order" line between
  auxiliary calls that belong to different sessions or agents.
- Switching the timeline's fold mode now resets the auxiliary aggregate cards too. Expanding one by
  hand, then using "expand all turns" and "fold by turn", used to leave that group scattered — the
  fold button looked like it did not apply to auxiliary calls. Only the turn cards were being reset;
  the aggregate cards were added later and never wired into the mode switch.

## v0.4.23 - 2026-09-02

### Added

- New request kind `notify_eval`: the check Claude Code runs while you are away to decide whether
  to notify you. It used to show up as `other`.

### Fixed

- The turns Claude Code starts by itself — suggestion completion, away review, internal search
  dispatch — are no longer counted as mainline; they now sit with the auxiliary calls. Claude Code
  does not record them in its own conversation log either, and turn counts now line up with that
  log (they used to be 70% too high). Background task notifications are not in this group: Claude
  Code does treat those as real turns.
- The `quota_probe` and `hook_eval` labels in the aux lane showed their raw English values; they
  now have Chinese and Japanese translations.
- The kind-dispatch order table in the message-anatomy guide was stuck at 260802 and missing two
  v0.4.22 rules (the `json_schema` official bit for titles, and the "no tools, not mainline"
  structural gate); it now matches what the code actually does.

## Earlier versions

v0.4.22 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the
[GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the
same notes per version.
