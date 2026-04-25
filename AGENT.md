# AGENT.md

Universal guide for all AI agents working on OmniAgent.

## What This Is

**OmniAgent** = HomeLab family AI assistant named **Cindy**.
Go API gateway + Python FastAPI brain + single PostgreSQL.
Serves LINE, Telegram, iMessage. No Redis, no ChromaDB.

Full engineering constitution: `omni-agent/AGENT.md`. Read it first.

## Quick Start

All commands from `omni-agent/`:

```bash
podman compose up -d --build          # Start all
podman compose build brain && podman compose up -d brain
curl http://localhost:8086/health     # Gateway
curl http://localhost:8000/health     # Brain
podman compose logs -f brain
```

## Environment

```bash
cd omni-agent && cp .env.example .env
# Fill: ANTHROPIC_API_KEY, GEMINI_API_KEY/OAuth, POSTGRES_*, LINE_*, TELEGRAM_*
```

## Testing

No automated runner. Manual scripts + phase acceptance criteria.

```bash
python test_router.py    # ModelRouter routing
python test_self_id.py   # Cross-platform identity
```

## Architecture (Brief)

```
External → Security Gateway (Synology) → Go Gateway (Debian) → Python Brain → PostgreSQL
                                                                    ↕ pgvector
```

Three nodes: Synology NAS (WAF), Debian 13 (Compute), Mac Mini M4 (Local LLM).

Full architecture diagram in `omni-agent/AGENT.md §1`.

## Key Constraints

- PostgreSQL only data layer. No Redis/ChromaDB.
- System prompt = Markdown. No raw JSON/SQL.
- Use vendor SDKs (anthropic, google-genai, openai). Not LangChain wrappers.
- Schema first. Confirm DB changes before app code.
- HomeLab scale. Clarity > performance.
- Shell: `vi` not nano.

## OpenSpec Workflow

Feature development uses OpenSpec. Specs at `omni-agent/openspec/specs/`.
Changes at `omni-agent/openspec/changes/`.

Commands: `explore`, `propose`, `apply`, `archive`.

See `omni-agent/AGENT.md §7` for full workflow.
