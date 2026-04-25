# Phase 4 Implementation Plan — Unified Identity + Skills Server + Proactive Agent

Implementing a unified identity system based on UUIDs, a new Go-based Skills Server for HomeLab automation (Cockpit, WOL), a multi-step LangGraph flow (PLAN-CONFIRM-EXECUTE-REPORT) in Brain, and proactive agent features (StressManager escalation and Stranger reports).

## User Review Required

> [!IMPORTANT]
> **Priority**: As requested, **Memory Migration** (Unified Identity Schema) will be the first task executed. All other components will be synced after the schema is updated.
> **Cockpit Auth**: Basic Auth (Username/Password) will be implemented using `COCKPIT_USER` and `COCKPIT_PASSWORD` from `.env`.
> **Stranger Policy**: To save tokens, a fixed polite rejection message will be pulled from `TELEGRAM_STRANGER_REPLY` in `.env`.
> **Confirmation Logic**: The `confirm:pending:{user_id}` state in `home_context` will include a JSON payload with `plan_id`, `timestamp`, `action_summary`, and `timeout`.

## Proposed Changes

---

### 1. Database Schema & Migration (PRIORITY 1)

New schema will decouple platform IDs from the internal User ID (UUID). This will be completed before any code changes.

#### [NEW] [002_unified_identity.sql](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/db/migrations/002_unified_identity.sql)
- Create `users` table (UUID, name, role, etc.).
- Create `telegram_accounts` and `line_accounts` tables.
- **Migration Logic**:
    - Insert into `users` from `family_members`.
    - Insert into `line_accounts` from `family_members` (mapping `line_id` to new UUID).
    - Update `conversations.user_id` from `line_id` to matching UUID.
    - Update `memory_embeddings.user_id` from `line_id` to matching UUID.
- Drop `family_members` table.

#### [NEW] [003_skills_strangers.sql](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/db/migrations/003_skills_strangers.sql)
- Create `stranger_knocks` table for logging unauthorized attempts.

---

### 2. Gateway Service (Go)

Upgrading identity handling and bootstrapping.

#### [MODIFY] [main.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/gateway/cmd/server/main.go)
- Add bootstrap logic: If no admin exists and `TELEGRAM_ADMIN_CHAT_ID` is set, create the first admin user.

#### [MODIFY] [telegram.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/gateway/internal/handler/telegram.go)
- Replace `TELEGRAM_ALLOWED_CHAT_IDS` check with a DB query to `telegram_accounts`.
- Handle strangers: Log to `stranger_knocks`, return `TELEGRAM_STRANGER_REPLY` from `.env`, and do **not** queue the message.
- Include `user_id` (UUID) in the `StandardMessage` payload sent to Brain.

---

### 3. Skills Server (Go)

A new container providing HomeLab automation capabilities.

#### [NEW] [skills/](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/skills/)
- Initialize Go project.
- `main.go`: HTTP server on port 8001.
- `handler/wol.go`: Wake-on-LAN implementation.
- `handler/cockpit.go`: Cockpit REST API wrapper (CPU, RAM, Disk, Restart Service).
- `handler/home_assistant.go`: Stub returning 501.

---

### 4. Brain Service (Python)

Implementing the agentic flow and proactive features.

#### [NEW] [graph.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/graph.py)
- LangGraph state machine: `PLAN` -> `CONFIRM` (if write op) -> `EXECUTE` -> `REPORT`.
- Integration with the `skills` server via HTTP.

#### [MODIFY] [main.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/main.py)
- Route `/chat` through the LangGraph agent.
- Background task: Stranger summary push to admin (Default: 21:00, stored in `home_context` key `setting:stranger_report_time` so it can be modified by the agent).
- Background task: Proactive StressManager escalation (proposal to upgrade model).
- Logic to listen for "CONFIRM" responses from users.

#### [MODIFY] [loader.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/soul/loader.py)
- Update to fetch current system context (incl. pending escalations/confirmations) for system prompt injection.

---

### 5. Infrastructure

#### [MODIFY] [.env.example](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/.env.example)
- Add `TELEGRAM_ADMIN_CHAT_ID`, `SKILLS_URL`.
- Add `COCKPIT_URL`, `COCKPIT_USER`, `COCKPIT_PASSWORD`.
- Add `TELEGRAM_STRANGER_REPLY` (Fixed rejection text).
- Add `BRAIN_UPGRADE_MODEL` (e.g., `claude-opus-4-6`).

## Open Questions

(All previous questions resolved)
- **Migration Verification**: I will run a count check on `users` vs `family_members` to ensure no data loss during the UUID transition.

## Verification Plan

### Automated Tests
- `podman compose up` and verify all 4 containers start.
- `curl http://skills:8001/health` from within the brain container.
- Unit tests for WOL MAC address validation.
- Migration health check: verify `users` table content after migration.

### Manual Verification
- Send message from unauthorized Telegram account -> verify it doesn't reach Brain and shows stranger message.
- Send "Wake up my PC" -> verify PLAN output and EXECUTE call to skills.
- Simulate StressCritical in `stress_logs` -> verify Admin receives upgrade proposal on Telegram.
- Trigger a service restart -> verify CONFIRM step is triggered and waits for user input.
