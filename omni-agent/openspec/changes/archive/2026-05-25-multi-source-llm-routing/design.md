## Context

`LocalClient` connects to a local MLX server via OpenAI-compatible `/v1/chat/completions`. The existing code reads `MLX_BASE_URL` (default `http://mac-mini.local:8086/v1`) and `MLX_MODEL` (default `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit`) — both point at a decommissioned setup. chrysoberyl (MacBook Pro M4) now runs Rapid-MLX serving `gemma-4-26b`, benchmarked at 34.5 tok/s / 120 ms TTFT (no-think) / ~2.2 s TTFT (think). The LocalClient contract (OpenAI-compat endpoint, `AsyncOpenAI` client) is unchanged and requires no rewrite.

## Goals / Non-Goals

**Goals:**
- Reconnect `local` provider to chrysoberyl (`100.88.136.117:8000/v1`)
- Surface Gemma 4's thinking capability as an opt-in per routing rule, consistent with existing `thinking_budget` pattern in `gemini` / `gemini_oauth`
- Document `MLX_BASE_URL` / `MLX_MODEL` env vars in `.env.example`

**Non-Goals:**
- NVIDIA NIM provider (separate stretch item)
- Claude persona routing rule (pending Agent SDK decision)
- Multi-model co-residence testing (Qwen 3.6 not yet validated)
- Any changes to the router, fallback chain, or upgrade logic

## Decisions

### D1 — Tailscale IP as config default, env override preserved

Use `http://100.88.136.117:8000/v1` as the new `MLX_BASE_URL` default in `.env.example` and `routing_config.json`. The `LocalClient` already respects `os.environ.get("MLX_BASE_URL")`, so operators can override to LAN IP (`192.168.68.81:8000/v1`) without code changes.

**Alternative considered**: hardcode LAN IP only. Rejected — Tailscale works across networks and is already confirmed direct-path at 38 ms over LAN.

### D2 — `enable_thinking` via `extra_body`, not a new parameter

vLLM and Rapid-MLX both accept `enable_thinking` inside `extra_body` on `/v1/chat/completions`. LocalClient passes this through `AsyncOpenAI(...).chat.completions.create(extra_body={"enable_thinking": ...})`. No API surface change to `ModelClient.chat()` — the flag is resolved inside `LocalClient` from a constructor argument.

**Alternative considered**: add `enable_thinking` to `ModelClient.chat()` signature. Rejected — other clients (Claude, Gemini) don't use this flag; keeping it LocalClient-internal avoids a leaky abstraction.

### D3 — `thinking_budget` in routing_config.json, same pattern as Gemini

`routing_config.json` local provider block gains an optional `thinking_budget` field (int, -1 = no thinking, 0 = thinking off, >0 = budget). `LocalClient.__init__` reads this from the config loader. Routing rules can set `thinking_budget` per rule, consistent with existing Gemini rules.

## Risks / Trade-offs

- [chrysoberyl offline] → `health_check: true` in routing_config already gates the provider at startup; ModelRouter falls back to `gemini_oauth`. No regression.
- [Tailscale tunnel drop during session] → The health check runs at startup only, not per-request. A mid-session tunnel drop will surface as a timeout, not a graceful fallback. Acceptable for now; per-request health check is a future hardening item.
- [Rapid-MLX `enable_thinking` API stability] → Rapid-MLX is pre-1.0; the `extra_body` field name could change. Isolated to `LocalClient`, easy to patch.

## Migration Plan

1. Update `.env.example` — add `MLX_BASE_URL` / `MLX_MODEL` with chrysoberyl values
2. Update `.env` — set actual values (Tailscale IP)
3. Patch `LocalClient` — add `thinking_budget` constructor arg, pass `extra_body` when > 0
4. Update `routing_config.json` — `local` provider block: new model + optional `thinking_budget`
5. Restart `brain` container — health check will confirm chrysoberyl reachable; `local` provider enables

Rollback: revert `.env` `MLX_BASE_URL` to any reachable endpoint or set `"enabled": false` on `local` provider.
