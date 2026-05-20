---
slug: multi-source-llm-routing
status: idea
domain: llm
size: L
priority: P1
created: 2026-05-20
---

# Multi-Source LLM Routing (Local Engine + NVIDIA RAG + Claude Persona Layer)

## Why
Cindy currently routes across Gemini OAuth / Gemini API / Claude / local MLX, but the local
provider is a stale Llama-3.1-8B stub, Claude sits only at the bottom of the fallback chain
(tie-break, not persona), and there is no heavy-RAG provider despite a 6-month free NVIDIA
window now available. The local Mac Mini was reinstalled, so the local engine is a clean
rebuild with no migration baggage — a one-time chance to pick the right serving engine before
committing. Without this, Cindy underuses free compute budget and has no principled home for
high-touch persona responses.

## What (high-level)
Extend the existing ModelRouter (it is the sole routing layer — LiteLLM was removed in Phase 2)
with two new provider classes and a persona routing rule, without redesigning routing itself.
Outcomes: (1) a chosen local MLX serving engine handles the local tier and multi-round
tool-call work for "fetch data / pull files / check records" tasks; (2) an NVIDIA NIM provider
carries heavy document RAG during the free window, with a named exit plan; (3) Claude is
promoted from fallback-only to a deliberate persona-highlight provider via a dedicated routing
rule, not just a reordered fallback chain. All routing decisions stay config-driven in
routing_config.json, and the ModelRouter remains the single owner of any cloud-escalation
decision.

## Acceptance hints
- The local provider connects over an OpenAI-compatible endpoint, so the existing LocalClient
  contract is preserved (engine swap requires no Brain client rewrite).
- The selected local engine has its built-in cloud-routing / auto-escalation disabled; the
  ModelRouter fallback_chain remains the only path to the cloud (no dual-brain black box).
- A new routing rule maps persona-highlight intent to the Claude provider, distinct from
  Claude's existing position in the fallback_chain.
- An NVIDIA NIM provider is registered and reachable for document-RAG long-context tasks.
- ModelRouter retains observability into the local tier (local-hit rate, cloud-escalation
  rate, cache-hit rate) so the local engine never becomes an opaque box.

## Open questions
- Local engine choice: leaning Rapid-MLX (only engine that advertises automatic recovery from
  quantized multi-round tool-call degradation, and CLI-first which fits headless SSH), with its
  cloud-routing disabled. oMLX is the fallback if Rapid-MLX cannot hold two small models
  resident at once. To be confirmed by M4 testing.
- Can the chosen engine keep two mid/small models (e.g. Gemma 4 + Qwen 3.6 class) co-resident
  on M4 32GB with zero swap latency? This is Rapid-MLX's weak spot and a hard requirement —
  test-only answer.
- Does the tool-call degradation auto-recovery actually hold for the chosen models (Gemma 4 /
  Qwen 3.6) under real fetch/file/record workloads, not just the vendor's benchmark claim?
- Claude persona layer: standard /v1/messages provider vs Agent SDK (claude -p) path? The
  6/15 free Agent SDK monthly allowance is hard-capped, non-rolling, and pay-as-you-go after
  depletion — decide whether the persona layer routes through it or stays on the OAuth/API path.
- NVIDIA NIM exit plan: when the 6-month free window closes, fall back to local or convert to
  paid? Name the trigger and the target.
- After 6/15, recalibrate the complexity-escalation threshold against the real Agent SDK
  allowance numbers (the existing 20/day upgrade quota assumed Gemini Pro economics).
- Memory correction needed: project memory still describes "LiteLLM as unified routing layer" —
  this is stale (removed Phase 2). Flag for memory update during grooming.

## Links
- Roadmap: openspec/backlog/ROADMAP.md (no precise anchor — spans current llm work; flag for next ROADMAP update)
- Related spec: openspec/specs/llm/spec.md
- Depends on: NONE
