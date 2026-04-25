# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

**Core engineering guide: `AGENT.md`.** Read it before any architectural change.
**Detailed Claude supplement: `omni-agent/CLAUDE.md`.**

## Project Overview

**OmniAgent** = HomeLab family AI assistant named **Cindy**.
Go API gateway + Python FastAPI brain + single PostgreSQL.
Unifies LINE, Telegram, iMessage with multi-provider LLMs.

## Running the System

All commands from `omni-agent/`:

```bash
podman compose up -d --build
podman compose build brain && podman compose up -d brain
curl http://localhost:8086/health   # Gateway
curl http://localhost:8000/health   # Brain
podman compose logs -f brain
podman compose down
```

## Environment

```bash
cd omni-agent && cp .env.example .env
# Fill: ANTHROPIC_API_KEY, GEMINI_API_KEY/OAuth, POSTGRES_*, LINE_*, TELEGRAM_*
```

DB migrations auto-run from `db/migrations/*.sql` on first startup.

## Testing

No automated runner. Manual scripts:

```bash
python test_router.py    # ModelRouter routing
python test_self_id.py   # Cross-platform identity
```

## OpenSpec Workflow

Feature development uses spec-driven OpenSpec workflow.
Use slash commands in `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/opsx-explore` | Think mode |
| `/opsx-propose` | Create change proposal |
| `/opsx-apply` | Implement tasks |
| `/opsx-archive` | Archive completed change |

## Key Constraints

- **PostgreSQL only.** No Redis, no ChromaDB.
- **System prompt = Markdown.** Not JSON/SQL.
- **Vendor SDKs** (anthropic, google-genai, openai). Not LangChain wrappers.
- **Schema first.** Confirm DB changes before app code.
- **Shell:** `vi` not nano.
