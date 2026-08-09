# Changelog

> Full notes for released versions live in [`CHANGELOG-history.md`](CHANGELOG-history.md).

## Project Overview

> Position / current status / next steps — the AI-onboarding snapshot. Navigation only; key decisions that are rules or invariants live in the local CLAUDE.md (developer conventions). Issue paths in entries below refer to local maintenance records (gitignored, not in this repo).

- **Position**: A local MITM-proxy desktop app that transparently records the full HTTP traffic between Claude Code and its upstream endpoint, surfacing the wire-level dimension that jsonl logs and OTLP telemetry cannot see. Dual mode: a GUI for humans, and a `serve` subcommand that exposes a headless HTTP API so an AI agent can drive its own inspection — the agent-facing manual ships inside the binary (`--help`, and `GET /api/ai-guide` once running), so no repository is needed to use it from an agent.
- **Current status**: **v0.4.13 released** (2026-08-09) — a same-day hotfix for the in-app updater that shipped in v0.4.11. Its Download button gave no feedback for the first silent seconds, the progress poller stopped 500ms in, and every re-click spawned another download thread: one real session fired **13 concurrent threads writing the same `.part`**, and the first finisher's rename failed with "file in use by another process" — from its own siblings. Downloads are now single-flight under a lock (`starting` phase, repeats get `already_running` and the UI reattaches), the staging file is unique per attempt, and clicking shows the progress bar immediately. **Upgrading from v0.4.11**: prefer "Open releases page" and swap the file manually, or click Download **once** and wait — do not re-click (the old UI carries the bug; the fix ships in this version). The previous release, v0.4.12, reworked the sequence diagram: turns now distinguish who started them (37% of wire "turns" are Claude Code talking to itself), auxiliaries aggregate per turn, and turns plus auxiliaries fold manually. **Heads-up for macOS upgraders** (unchanged since v0.4.2): the bundle was renamed `CCWireAnalyzer.app` → `cc-wire-analyzer.app`; the old one in `/Applications` is not replaced, delete it yourself.
- **Next steps**:
  1. **Close the self-improvement loop.** `/api/diagnose/trends` now answers "new or recurring?" reliably, but turning a recurring pattern into a check is still manual — `effort_max_rejected_upstream` exists because a human noticed a recurring failure and wrote a rule for it. Automating that half is what makes the radar and the trends more than a reading exercise.
  2. **Identity residual** (deferred): interactive-mode (`cc_entrypoint=cli`) subagents still lack a hand-verified capture. Historical captures supply statistical evidence (225 requests, all carrying the flag, no counterexample), but that is not the same as a session captured and checked against ground truth.
  3. The recording-blind-spot audit (protocol side and capability side) closed across v0.4.3–v0.4.6; method in `docs/reference/开发约定.md` §2.5 and unit 0 of `docs/methodology/同类工具构建手册.md`.

## Unreleased

- **Public presence launched.** Bilingual English/Chinese GitHub Pages site (canonical, hreflang, Open Graph, SoftwareApplication JSON-LD, sitemap), a 1280×640 social preview, and Google Search Console ownership verified. Three READMEs refreshed with the full product name, real `git clone` and `releases/latest` entry points, and platform/local-run trust signals (`c64dbe7`, `216b10d`). Community promotion deferred. The from-scratch reproducible tutorial lives in `promo/` (gitignored, local only).

## v0.4.13 - 2026-08-09

### Fixed

- **The in-app updater's Download button is no longer a leap of faith: locked single-flight + immediate feedback.** On v0.4.11, clicking Download looked dead for several seconds — the checksum-manifest fetch and the GitHub connect (both seconds through a proxy) all happened before any progress phase existed; worse, the progress poller treated that pre-connect window as a terminal state 500ms in and stopped, reverting the UI to an untouched-looking Download button that invited re-clicks — and every re-click passed the hollow duplicate-check and spawned another download thread. One real session fired **13 concurrent download threads writing the same `.part`**; the first finisher's rename then tripped over its own siblings' file handles, surfacing "the file is in use by another process" (WinError 32) — the file was held not by some other program but by our own threads.

  The fix gives each layer its own job: the backend registers the task under a lock as a `starting` phase *before* touching the network (repeat calls get `already_running`, and the UI reattaches the progress bar to the running task instead of erroring); the staging file name is unique per attempt (defence in depth — should the guard ever be bypassed again, two writers never share a file, so rename can never hit a sibling's handle); the frontend disables the button and optimistically renders the `starting` progress bar on click. Two adjacent bugs fixed along the way: checking for updates mid-download no longer clobbers the running task's phase back to `idle` (which used to stop the poller), and the checksum-manifest fetch moved from the request handler into the download thread (it was part of the silent seconds). Verified end-to-end with real clicks: five rapid clicks spawn zero extra threads, a mid-download update check leaves the progress bar alone, and the install entry appears once SHA-256 verification passes.

  **Upgrade guidance for v0.4.11 users**: the old version's updater UI carries this bug (the fix ships in the new version), so the reliable path is "Open releases page" and swap the file manually; or click Download **once** and wait patiently (the download is genuinely running — the UI just won't tell you), and do not re-click.

## Earlier versions

v0.4.12 and earlier: [CHANGELOG-history.md](CHANGELOG-history.md) — or the [GitHub Releases page](https://github.com/FuHehe12/cc-wire-analyzer/releases), which carries the same notes per version.
