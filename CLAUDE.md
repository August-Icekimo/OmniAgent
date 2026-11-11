# CLAUDE.md

**OmniAgent** = HomeLab family AI assistant **Cindy**: Go gateway + Python FastAPI brain + single PostgreSQL, serving LINE / Telegram / iMessage.

Everything lives in `omni-agent/`:
- **`omni-agent/AGENT.md`** — engineering constitution (architecture, rules, OpenSpec + backlog workflow, ops commands). Read before any architectural change.
- **`omni-agent/CLAUDE.md`** — Claude Code supplement (confirmation rules, key files).
- OpenSpec slash commands (`/opsx-*`) live in `omni-agent/.claude/commands/` — launch Claude Code from `omni-agent/` to use them.

## Key Constraints

- **PostgreSQL only.** No Redis, no ChromaDB.
- **System prompt = Markdown.** Not JSON/SQL.
- **Vendor SDKs** (anthropic, google-genai, openai). Not LangChain wrappers.
- **Schema first.** Confirm DB changes before app code.
- **Shell:** `vi` not nano.
