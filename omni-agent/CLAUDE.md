# CLAUDE.md — Claude Code Supplement

> This file is for **Claude Code** only.
> Core engineering guide: **`AGENT.md`** (read it first).
> Cindy's personality: **`SOUL.md`**.

---

## Claude Code Behavior

### Confirmation Rules
- **Ask before** installing new packages or dependencies.
- **Ask before** modifying DB schema or migrations.
- **Ask before** changing `routing_config.json` provider settings.
- **Just do it** for code fixes, refactors, and test additions.

### Commit Messages
- Use **Traditional Chinese** for commit messages.
- Format: `<type>(<scope>): <description>`
- Example: `feat(brain): 新增 FileAnalyzer 附件路由`

### Safe Auto-Run Commands
```
podman compose logs -f <service>
curl http://localhost:*/health
cat / ls / find / grep
psql -c "SELECT ..." (read-only queries)
```

---

## OpenSpec Commands (Claude Code)

Use these slash commands for spec-driven development:

| Command | Purpose |
|---------|---------|
| `/opsx-explore` | Think mode — read code, discuss, no implementation |
| `/opsx-propose` | Create change with proposal + design + tasks |
| `/opsx-apply` | Implement tasks from a change |
| `/opsx-archive` | Archive completed change |

Commands located at `.claude/commands/opsx-*.md`.

---

## LLM Provider Config

Edit `brain/config/routing_config.json` to change routing.
Default: `gemini_oauth` (Gemini 2.5 Pro via OAuth).

**Never hardcode model names** in application code. Always use routing config.

---

## Key File Locations

| What | Where |
|------|-------|
| Engineering constitution | `AGENT.md` |
| Cindy's soul | `SOUL.md` |
| API entry (Brain) | `brain/main.py` |
| LangGraph agent | `brain/agent/graph.py` |
| LLM routing | `brain/llm/router.py` |
| Routing config | `brain/config/routing_config.json` |
| Gateway entry | `gateway/cmd/server/main.go` |
| DB schema | `db/SCHEMA.md` + `db/migrations/` |
| Specs (source of truth) | `openspec/specs/<domain>/spec.md` |
