## 1. Environment Config

- [x] 1.1 Add `MLX_BASE_URL=http://100.88.136.117:8000/v1` to `.env.example` (LLM section)
- [x] 1.2 Add `MLX_MODEL=gemma-4-26b` to `.env.example`
- [x] 1.3 Set `MLX_BASE_URL` and `MLX_MODEL` in `.env` with Tailscale values

## 2. LocalClient — Thinking Mode

- [x] 2.1 Add `thinking_budget: int = -1` constructor arg to `LocalClient.__init__`
- [x] 2.2 In `LocalClient.chat()`, pass `extra_body={"enable_thinking": True}` when `thinking_budget > 0`, omit `extra_body` otherwise
- [x] 2.3 Update `LocalClient` docstring to note Gemma 4 thinking behaviour and TTFT cost

## 3. Routing Config

- [x] 3.1 Update `routing_config.json` `local.model` → `gemma-4-26b`
- [x] 3.2 Add `"thinking_budget": -1` to `local` provider block (thinking off by default)
- [x] 3.3 Verify `config_loader.py` passes `thinking_budget` through to `LocalClient` constructor; patch if not

## 4. Verify

- [x] 4.1 `curl http://100.88.136.117:8000/v1/models` returns `gemma-4-26b` — confirm endpoint live
- [x] 4.2 Restart `brain` container; check logs confirm local provider health check passes
- [x] 4.3 Send a short message routed to `local`; confirm response comes from `gemma-4-26b`
