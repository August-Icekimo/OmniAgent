## Why

The local provider is a stale Llama-3.1-8B stub pointing at a decommissioned endpoint (`mac-mini.local:8086`); it has been effectively dead since the Mac Mini was reinstalled. chrysoberyl (MacBook Pro M4) now runs Rapid-MLX serving `gemma-4-26b` at `100.88.136.117:8000/v1`, benchmarked at 34.5 tok/s with 120 ms steady-state TTFT — a substantial free-compute tier that Cindy cannot use until the config is updated.

## What Changes

- Update `local` provider endpoint from `mac-mini.local:8086/v1` → `100.88.136.117:8000/v1` (Tailscale, chrysoberyl)
- Update `local` provider model from `mlx-community/Meta-Llama-3.1-8B-Instruct-4bit` → `gemma-4-26b`
- Add `enable_thinking` parameter support to `LocalClient` (Gemma 4 supports thinking mode; 18× TTFT cost when enabled — must be opt-in per routing rule)
- Add `MLX_BASE_URL` and `MLX_MODEL` to `.env.example` (currently undocumented)
- Update `routing_config.json` `local` provider block with new model and optional `thinking_budget` field

## Capabilities

### New Capabilities

- `local-thinking`: LocalClient gains an `enable_thinking` flag, surfaced as an optional `thinking_budget` field in routing_config.json, consistent with the existing `gemini` / `gemini_oauth` pattern.

### Modified Capabilities

- `llm`: local provider health check target, model identity, and endpoint change. Routing rules that dispatch to `local` now reach a Gemma 4 thinking model instead of a Llama-3.1 non-thinking model.

## Impact

- `brain/llm/local_client.py` — add `enable_thinking` / `extra_body` support
- `brain/config/routing_config.json` — update `local` provider block
- `omni-agent/.env.example` — add `MLX_BASE_URL`, `MLX_MODEL`
- `omni-agent/.env` — set actual Tailscale values
- No DB schema changes. No gateway changes. No other LLM clients affected.
