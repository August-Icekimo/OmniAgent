# Omni-Agent — Engineering Constitution

> Core guide for all AI agents working on this project.
> Read fully before any architectural change. No exceptions.

---

## 0. What This Is

**Omni-Agent** = HomeLab family AI assistant named **Cindy**.
Role: family butler / household manager. Serves entire family, not single user.

Personality defined in `SOUL.md`. Read it. Internalize it.

---

## 1. Three-Layer Architecture

```
Real World (LINE / Telegram / iMessage)
  │ HTTPS (443)
  ▼
┌─────────────────────────────────────────┐
│  Security Gateway (Synology NAS)        │
│  · Caddy + Coraza WAF                  │
│  · CrowdSec (global threat intel)      │
│  · Guacamole (remote admin)            │
└───────────────┬─────────────────────────┘
                │ Proxy Pass (internal net)
                ▼
┌─────────────────────────────────────────┐
│  The Senses — Go API Gateway (Debian)   │
│  · Webhook signature verification       │
│  · Convert to StandardMessage{}         │
│  · Async reply (LINE 3s timeout)        │
│  · StressManager (self-aware overload)  │
└───────────────┬─────────────────────────┘
                │ HTTP (StandardMessage JSON)
                ▼
┌─────────────────────────────────────────┐
│  The Brain — Python FastAPI + LangGraph │
│  · Conversation state (LangGraph)       │
│  · SoulLoader: build system prompt      │
│  · ModelRouter: vendor SDK routing      │
│    ├─ Claude (anthropic SDK + cache)    │
│    ├─ Gemini (google-genai + OAuth)     │
│    └─ Local MLX (openai SDK → Mac Mini) │
│  · MCP Skills invocation                │
│  · RAG memory retrieval (pgvector)      │
└───────────────┬─────────────────────────┘
                ▼
┌─────────────────────────────────────────┐
│  The Hippocampus — PostgreSQL (only DB) │
│  · pgvector: long-term semantic memory  │
│  · SKIP LOCKED: message queue           │
│  · LISTEN/NOTIFY: real-time push        │
│  · JSONB: family data, device state     │
│  · stress_logs: cerebellum diary        │
└─────────────────────────────────────────┘
```

### Physical Nodes

| Node | Role | Key Services |
|------|------|-------------|
| Synology NAS (DSM) | Front-door | Caddy + WAF, CrowdSec, Guacamole |
| Debian 13 | Compute | Senses, Brain, Hippocampus (Podman) |
| Mac Mini M4 | Inference | mlx-lm, OpenAI-compatible API |

---

## 2. Immutable Engineering Decisions

### 2.1 PostgreSQL = Only Data Layer

No Redis. No ChromaDB. No external queues. Everything in one PG instance.

| Replaced | With | Why |
|----------|------|-----|
| SQLite | `conversations` table | No write lock, unified |
| ChromaDB | pgvector extension | One less container |
| Redis Queue | SKIP LOCKED + LISTEN/NOTIFY | Messages persist in table |

**Trade-off accepted:** Queue throughput < Redis at >100s/sec. HomeLab never hits this.

**Backup = one command:** `pg_dump omni_agent`

### 2.2 SOUL.md = Markdown, Family Data = PostgreSQL

```
SOUL.md (git-managed, Markdown)
  └─ Personality, values, tone, boundaries
     → Rarely changes. Needs version control. LLM comprehends best.

PostgreSQL: family_members + home_context (JSONB)
  └─ Member info, permissions, device state, preferences
     → Dynamic. Programmatic access. Fine-grained auth.

soul/loader.py
  └─ Read SOUL.md + query PG → render Markdown system prompt → inject LLM
```

**Key insight:** LLM follows Markdown instructions better than JSON. JSON = data scanning, Markdown = behavior internalization.

**FORBIDDEN:** Feed raw JSON or SQL output as system prompt.

### 2.3 StressManager — Self-Aware Overload

Go gateway has adaptive stress sensor. Two response strategies:

**Stress levels:** Calm → Busy → Overload → Critical

**Strategy A — Complain & Write Diary (Graceful Degradation):**
Delay low-priority tasks. Reply with personality. Log to `stress_logs` with mood field.

**Strategy B — Boss Pays More (Model Escalation):**
Switch to stronger model via ModelRouter. Approval mode: Auto / SemiAuto / Manual.

**Soul feedback loop:** `stress_logs` history → `soul/loader.py` → inject into SOUL.md dynamic section → LLM gains self-history awareness.

---

## 3. Database Schema (Key Tables)

Full DDL in `db/migrations/`. Reference `db/SCHEMA.md`.

| Table | Purpose |
|-------|---------|
| `users` | Unified identity (UUID, name, role, access_level) |
| `line_accounts` | LINE ID → user mapping |
| `telegram_accounts` | Chat ID → user mapping |
| `conversations` | Recent dialogue (JSONB array) |
| `memory_embeddings` | pgvector semantic memory (vector 1536) |
| `message_queue` | SKIP LOCKED queue (priority, status, stress_level) |
| `stress_logs` | Cerebellum diary (level, metrics, mood) |
| `home_context` | Device/environment state (JSONB, active flag) |
| `oauth_tokens` | Gemini OAuth token cache |

**Rule:** Confirm schema changes BEFORE writing app code. Always.

---

## 4. Project Structure

```
omni-agent/
├── compose.yml                    # Podman-compatible
├── .env / .env.example
├── AGENT.md                       # This file (engineering constitution)
├── CLAUDE.md                      # Claude Code supplement
├── GEMINI.md                      # Gemini/Antigravity supplement
├── SOUL.md                        # Cindy's soul (git-managed)
│
├── gateway/                       # The Senses (Go)
│   ├── cmd/server/main.go
│   └── internal/
│       ├── handler/               # line, telegram, bluebubbles, health
│       ├── model/standard_message.go
│       ├── stress/manager.go      # Cerebellum
│       ├── forwarder/brain.go
│       ├── queue/queue.go
│       └── messenger/messenger.go
│
├── brain/                         # The Brain (Python)
│   ├── main.py                    # FastAPI entry
│   ├── agent/
│   │   ├── graph.py               # LangGraph state machine
│   │   ├── proactive.py           # Proactive push
│   │   └── prompts/               # system_prompt.py, tools_prompt.py
│   ├── llm/                       # ModelRouter + vendor SDKs
│   │   ├── base.py                # ModelClient ABC
│   │   ├── claude_client.py       # anthropic SDK + prompt caching
│   │   ├── gemini_client.py       # google-genai SDK + context caching
│   │   ├── oauth_gemini_client.py # OAuth 2.0 Gemini
│   │   ├── local_client.py        # openai SDK → Mac Mini MLX
│   │   └── router.py              # Routing + escalation
│   ├── config/
│   │   ├── routing_config.json    # Provider rules
│   │   └── config_loader.py
│   ├── memory/
│   │   ├── short_term.py          # conversations table
│   │   └── long_term.py           # pgvector RAG
│   ├── skills/                    # MCP tool implementations
│   │   ├── file_analyzer.py
│   │   ├── wake_on_lan.py
│   │   ├── proxmox.py
│   │   └── home_assistant.py
│   └── soul/
│       ├── loader.py              # SOUL.md + DB → Markdown prompt
│       └── templates/context.md.jinja
│
├── skills/                        # Skills Server (Go)
│   ├── main.go
│   └── handler/
│
├── db/
│   ├── SCHEMA.md
│   └── migrations/*.sql
│
├── openspec/                      # OpenSpec workflow
│   ├── specs/                     # Source-of-truth specifications
│   │   ├── brain/spec.md
│   │   ├── gateway/spec.md
│   │   ├── identity/spec.md
│   │   ├── llm/spec.md
│   │   ├── memory/spec.md
│   │   ├── security/spec.md
│   │   ├── skills/spec.md
│   │   └── soul/spec.md
│   └── changes/
│       └── archive/               # Completed phase proposals/tasks
│
├── docs/                          # Legacy (deprecated, see openspec/)
├── groups/                        # Family/homelab group configs
├── memory/                        # PG data volume
└── scripts/
```

---

## 5. Development Phases (All Complete)

| Phase | Goal | Status |
|-------|------|--------|
| 1 | Go Gateway + PG Queue + StressManager skeleton | ✅ |
| 2 | Python Brain + vendor SDK adapters + ModelRouter | ✅ |
| 3 | Memory system + SoulLoader + stress diary | ✅ |
| 3.5 | Telegram platform integration | ✅ |
| 4 | Identity system + MCP Skills (WoL, Cockpit) | ✅ |
| 4a | Dynamic ModelRouter + routing_config.json | ✅ |
| 4b | File analysis + FileAnalyzer skill | ✅ |
| 4c | Gemini OAuth integration | ✅ |

Phase history archived at `openspec/changes/archive/`.

---

## 6. Development Rules

- **Incremental.** One feature at a time. No sprinting ahead.
- **Container-first.** Every service has Dockerfile. Whole system has compose.yml.
- **Error handling.** All HTTP/DB ops need retry + structured logging.
- **Shell.** Use `vi`, not nano.
- **No premature optimization.** HomeLab scale. Clarity > performance.
- **Schema first.** Confirm DB changes before writing app code.
- **Use vendor SDKs.** anthropic, google-genai, openai — not LangChain wrappers.
- **System prompt = Markdown.** Never raw JSON/SQL in prompt.
- **OpenSpec workflow.** Use `openspec/` for all spec-driven changes.
- **WIP limit (hard).** Maximum 1 active OpenSpec change at any time. `/opsx:propose` MUST refuse if `openspec list --json` shows ≥1 active change. No `--force` override. To start a new change, archive the current one first.

---

## 7. OpenSpec Workflow

All feature development follows OpenSpec spec-driven workflow.

### Structure
```
openspec/
├── specs/<domain>/spec.md    # Source of truth (WHEN/THEN format)
└── changes/
    ├── <active-change>/      # In-progress work
    │   ├── proposal.md       # What & why
    │   ├── design.md         # How (optional)
    │   └── tasks.md          # Implementation checklist
    └── archive/              # Completed changes
```

### Workflow Commands

| Command | Action |
|---------|--------|
| `explore` | Think mode. Read code, discuss, no implementation. |
| `capture` | Capture a new idea into `openspec/backlog/ideas/`. |
| `plan`    | Open a new sprint, select cards from `ready/`, produce sprint file. |
| `propose` | Create new change with proposal + design + tasks. |
| `apply`   | Implement tasks from a change. |
| `archive` | Archive completed change, sync delta specs. |

### Spec Domains
8 domains: `brain`, `gateway`, `identity`, `llm`, `memory`, `security`, `skills`, `soul`.

Each `spec.md` uses WHEN/THEN format. Example:
```markdown
### Requirement: <name>
#### Scenario: <scenario>
- **WHEN** <condition>
- **THEN** <expected outcome>
```

---

## 7.5 Backlog & Sprint Workflow

OpenSpec covers active and archived work. Backlog covers what is being **considered** and **scheduled**.

### Pipeline

```
ideas → ready → sprints (committed) → changes → changes/archive
        │       │                     │
        │       │                     └─ /opsx:propose (gated by WIP=1 + sprint membership)
        │       └─ /opsx:plan
        └─ /opsx:explore (grooming, conversational)
```

### Directory layout

```
openspec/backlog/
├── ROADMAP.md           # quarterly themes; reference during grooming
├── _templates/          # canonical templates for items and sprints
├── ideas/<slug>.md      # raw captures, low bar (why+what+domain required)
├── ready/<slug>.md      # groomed, ready to be committed (no open questions)
└── sprints/
    ├── <YYYY>-W<NN>.md  # current sprint
    └── archive/         # past sprints
```

### Phase rules

| Phase | Command | Required fields | WIP gate |
|-------|---------|-----------------|----------|
| Capture | `/opsx:capture` | why, what, domain | none |
| Groom | `/opsx:explore <slug>` | + acceptance hints, no open questions | none |
| Plan | `/opsx:plan` | sprint goals + committed cards | previous sprint must have retro filled |
| Propose | `/opsx:propose <slug>` | slug must exist in current sprint | WIP=1 hard limit |
| Apply | `/opsx:apply` | (uses existing tasks.md) | — |
| Archive | `/opsx:archive` | (existing flow + git rm ready card) | — |

### Sprint conventions

- **Length**: 2 weeks
- **Naming**: `<YYYY>-W<NN>.md` (ISO week, e.g. `2026-W17.md`)
- **Window**: Monday → Sunday + 13 days
- **Retro**: Filled manually at sprint end. `/opsx:plan` blocks until prior retro present.
- **No /opsx:retro command yet** — future enhancement, hook position reserved.

### Hard rules

1. `changes/<slug>/` MUST originate from a card in the current sprint's `Committed` (or confirmed `Stretch`) table.
2. Items in `ready/` MUST have empty `Open questions`.
3. `Domain:` field MUST be one of the 8 OpenSpec domains.
4. WIP=1: at most one non-archived `changes/<slug>/` at a time.
5. ROADMAP.md placeholders MUST be replaced with real themes before they are referenced from a ready card.
6. **Three-way command parity**: Updates to any `opsx` command MUST update all three sets (`.agent/`, `.gemini/`, `.claude/`) in the same commit.

---

## 8. Cross-Workspace Map

Two Git repos. Both needed for full context.

| Repo | Path | Role |
|------|------|------|
| **OmniAgent** | `/home/icekimo/gitWrk/OmniAgent` | Core brain + senses |
| **secure-gateway** | `/home/icekimo/gitWrk/secure-gateway` | Front-door security |

### secure-gateway
- Runs on Synology DSM Container Manager
- Traffic: Internet (443) → Caddy (DSM) → Debian 13 (Omni-Agent Gateway)
- Services: Caddy + Coraza WAF, CrowdSec, Guacamole

---

## 9. Operations Quick Reference

### Common Commands (Debian Node)
```bash
podman compose up -d --build          # Start all
podman compose build brain && podman compose up -d brain  # Rebuild one
podman compose logs -f brain          # Logs
podman compose down                   # Stop all
curl http://localhost:8086/health     # Gateway health
curl http://localhost:8000/health     # Brain health
```

### Database
```bash
psql -h localhost -U omni -d omni_agent
```

### Synology (secure-gateway)
```bash
ssh VivienLeigh "docker ps"
ssh VivienLeigh "docker logs --tail 50 <container>"
```

### Environment Setup
```bash
cp .env.example .env
# Fill: ANTHROPIC_API_KEY, GEMINI_API_KEY/OAuth, POSTGRES_*, LINE_*, TELEGRAM_*
```

DB migrations auto-run from `db/migrations/*.sql` on first startup.
