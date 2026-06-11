---
slug: antigravity-a2a-integration-path
status: idea
domain: brain
size: M
priority: P1
created: 2026-06-10
---

# Antigravity A2A Integration Path (SDK vs Subprocess CLI)

## Why
Phase 5.9 plans A2A orchestration via subprocess CLI, but agy's headless mode is
currently broken for exactly that pattern: `--print` silently drops stdout when
invoked from a non-TTY subprocess (google-antigravity/antigravity-cli#76), and
no conversation ID is surfaced, so a wrapper cannot maintain per-member threads
(#7). Building the delegation channel on this path risks shipping a feature that
fails silently in production and needs rework when the official path matures.

## What (high-level)
Cindy delegates outsourced work to Antigravity agents through a deliberate,
evaluated integration path. The official Google Antigravity SDK (Python,
preview, Apache 2.0 — same Agent Runtime as agy, with custom-tool registration,
MCP server support, declarative safety policies, lifecycle hooks, and subagent
spawning) is evaluated as the primary candidate against the original subprocess
CLI plan. The chosen path supports concurrent per-member work threads, honest
failure reporting, and headless 24/7 operation on the existing Brain stack.

## Acceptance hints
- (to be drafted during grooming)

## Open questions
- SDK auth model: personal OAuth vs Cloud project vs API key — quota and billing
  attribution must be verified before adoption (avoid another silent cost shift)
- SDK is in preview: what stability/GA signal do we wait for, if any?
- Overlap with the Hermes foreman: Hermes already ships an official skill for
  operating agy. Should Cindy integrate Antigravity directly, or only ever
  through the foreman? Does direct SDK integration make part of the foreman
  role redundant?
- Can the SDK's declarative safety policies and hooks map onto Mjolnir
  capability circles, or do they form a second, conflicting permission layer?
- The "craft memory vs people memory" dividing line: the SDK runs in Brain's
  process space — where does de-identification happen before work is handed
  to an Antigravity agent?
- If issues #76/#7 are fixed before Phase 5.9 lands, does subprocess CLI
  regain viability as a lighter-weight fallback, or is SDK-only cleaner?
- This card touches brain + llm + security. During grooming, decide whether
  to split or keep unified.

## Links
- Roadmap: openspec/backlog/ROADMAP.md#phase-59-agent-capabilities
- Related spec: openspec/specs/brain/spec.md
- Depends on: mjolnir-trust-model (creative-agency circle semantics),
  gemini-oauth-sunset-router-rework (auth/quota lessons apply directly)
