# CLAUDE.md — Claude Code Supplement

> Core engineering guide: **`AGENT.md`** (read it first). Cindy's personality: **`SOUL.md`**.

## Confirmation Rules

**Ask before:**
- installing new packages or dependencies
- modifying DB schema or migrations
- changing `brain/config/routing_config.json` provider settings

## Commit Messages

Traditional Chinese, `<type>(<scope>): <description>` — e.g. `feat(brain): 新增 FileAnalyzer 附件路由`. Use `/commit`.

## OpenSpec Commands

`/opsx-explore`, `/opsx-capture`, `/opsx-plan`, `/opsx-propose`, `/opsx-apply`, `/opsx-archive` — in `.claude/commands/`. Workflow and hard rules: `AGENT.md` §7–7.5 (any edit must update `.agent/`, `.gemini/`, `.claude/` together).

## LLM Routing

Configured only in `brain/config/routing_config.json` (fallback chain lives there). **Never hardcode model names** in application code.

## Key File Locations

| What | Where |
|------|-------|
| API entry (Brain) | `brain/main.py` |
| LangGraph agent | `brain/agent/graph.py` |
| LLM routing | `brain/llm/router.py` |
| Gateway entry | `gateway/cmd/server/main.go` |
| DB schema | `db/SCHEMA.md` + `db/migrations/` |
| Specs (source of truth) | `openspec/specs/<domain>/spec.md` |
