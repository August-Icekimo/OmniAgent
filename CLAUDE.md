# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**OmniAgent** is a HomeLab-deployed family AI assistant named **Cindy**. It unifies messaging platforms (LINE, Telegram, BlueBubbles/iMessage) with multi-provider LLMs via a Go API gateway and Python FastAPI brain. Everything persists to a single PostgreSQL instance — no Redis, no ChromaDB, no external queues.

The full engineering constitution (architecture decisions, schema, design rationale) lives at `omni-agent/CLAUDE.md` (Chinese). Read it before making architectural changes.

---

## Running the System

All commands run from `omni-agent/`:

```bash
# Start all services (gateway, brain, postgres, skills)
podman compose up -d --build

# Rebuild a single service
podman compose build brain && podman compose up -d brain

# Health checks
curl http://localhost:8086/health   # Gateway (queue depth)
curl http://localhost:8000/health   # Brain (service status)

# View logs
podman compose logs -f brain
podman compose logs -f gateway

# Stop everything
podman compose down
```

## Environment Setup

```bash
cd omni-agent
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, GEMINI_API_KEY/OAuth tokens,
#          POSTGRES_* credentials, LINE_* and TELEGRAM_* tokens
# Warning: If credentials are real values (not placeholders), you are in PRODUCTION. Keep them safe and secret.
```

Database migrations run automatically from `db/migrations/*.sql` on first startup.

## Testing

No automated test runner is configured. Tests are manual scripts and phase-based acceptance criteria:

```bash
# From repo root (requires .env or env vars set)
python test_router.py    # ModelRouter routing logic
python test_self_id.py   # Cross-platform identity mapping

# Phase acceptance criteria (Markdown checklists)
cat omni-agent/docs/test_phase*.md
```

---

## Architecture

### Three-Layer System

```
External (LINE / Telegram / iMessage)
  ↓ HTTPS
Security Gateway (Synology NAS)       — Caddy + Coraza WAF + CrowdSec
  ↓ Proxy pass (internal network)
The Senses — Go API Gateway            — omni-agent/gateway/
  ↓ HTTP StandardMessage{}
The Brain — Python FastAPI + LangGraph — omni-agent/brain/
  ↕ asyncpg
The Hippocampus — PostgreSQL           — single DB, pgvector for embeddings
```

**Physical:** Debian 13 node runs The Senses, The Brain, and PostgreSQL. Mac Mini M4 runs local MLX inference (OpenAI-compatible API at the `local` provider).

### Message Flow

1. Go gateway receives webhook, verifies platform signature
2. Converts to `StandardMessage{}` (`model/standard_message.go`)
3. Inserts into `message_queue` table (`SKIP LOCKED` prevents duplicate processing)
4. `BrainForwarder` background worker polls and POSTs to Brain `/chat`
5. Brain runs LangGraph state machine → returns reply text + metadata
6. `Messenger` module sends reply via LINE/Telegram API

### The Brain (Python) — `omni-agent/brain/`

- **Entry**: `main.py` — FastAPI app, initializes all subsystems on startup
- **LangGraph agent**: `agent/graph.py` — nodes: planner → reasoner → tool_router → executor → responder
- **LLM routing**: `llm/router.py` + `config/routing_config.json` — rules-based provider selection with complexity assessment and escalation
- **LLM providers**: `llm/claude_client.py`, `llm/gemini_client.py`, `llm/oauth_gemini_client.py`, `llm/local_client.py` — each wraps the vendor's official SDK
- **Personality**: `soul/loader.py` renders `SOUL.md` (static, git-managed) + dynamic DB context (stress logs, home events) into the system prompt via Jinja2
- **Memory**: `memory/short_term.py` (recent conversations from DB), `memory/long_term.py` (pgvector semantic search)

### The Gateway (Go) — `omni-agent/gateway/`

- **Entry**: `cmd/server/main.go`
- **Handlers**: `internal/handler/{line,telegram,bluebubbles}.go`
- **StressManager**: `internal/stress/manager.go` — tracks queue depth, P95 latency, error rate; triggers graceful degradation or model escalation
- **Messenger**: `internal/messenger/messenger.go` — platform-specific reply delivery

### LLM Provider Configuration

Edit `brain/config/routing_config.json` to change routing rules, provider enable/disable, upgrade thresholds, and fallback chains. Default route: `gemini_oauth` (Gemini 2.5 Pro via OAuth).

### Database

Single PostgreSQL instance. Key tables: `users`, `line_accounts`, `telegram_accounts`, `conversations`, `memory_embeddings` (pgvector), `message_queue`, `stress_logs`, `home_context`. Full schema in `db/SCHEMA.md`.

---

## Key Constraints

- **PostgreSQL is the only data layer.** No Redis, no ChromaDB, no external queues.
- **System prompt must be Markdown**, not raw JSON or SQL output — LLMs follow Markdown instructions better.
- **Use official vendor SDKs** (anthropic, google-genai, openai) — not LangChain wrappers — for LLM calls.
- **Schema first:** Confirm DB schema changes before writing application code for any new feature.
- **No premature optimization:** This is HomeLab scale; design for clarity, not millions of requests.
- **Development editor:** `vi` (not nano).
