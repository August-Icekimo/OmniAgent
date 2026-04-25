## Why

Phase 4 aims to:
1. Establish a unified identity system using UUIDs across different platforms.
2. Introduce an independent Go-based Skills Server for complex tasks like Cockpit management and Wake-on-LAN.
3. Implement a "Plan-Confirm-Execute-Report" multi-step dialogue flow using LangGraph.
4. Add proactive capabilities, such as proposing model upgrades during high system stress.

## What Changes

- `db/migrations/`: Added `002_unified_identity.sql` and `003_skills_strangers.sql`.
- `gateway/`: Updated Telegram handler to use DB identity lookup; added admin bootstrap logic.
- `skills/`: New Go service for executing skills (Cockpit, WoL).
- `brain/agent/graph.py`: LangGraph implementation for multi-step agent logic.
- `brain/main.py`: Integrated LangGraph and proactive background tasks.
- `brain/agent/proactive.py`: Logic for stranger summaries and stress-based upgrade proposals.

## Capabilities

### New Capabilities
- `identity`: Unified user management with cross-platform account mapping (Telegram, LINE).
- `skills`: Modular execution of home automation and server management tasks.

### Modified Capabilities
- `brain`: Upgraded from a simple LLM wrapper to a stateful LangGraph agent capable of planning and confirmation.
- `gateway`: Enhanced security through DB-backed identity verification and stranger tracking.

## Impact

- Requires new database tables and data migration.
- New `skills` service added to `compose.yml`.
- Proactive messages may be sent to admins via Telegram.

## Open Questions

- Cockpit API Auth: Verified as `COCKPIT_USER`/`COCKPIT_PASSWORD`.
- LangGraph Confirm Detection: Verified as keyword detection in `main.py` using `home_context` state.
- Upgrade Model: Verified as `gemini-2.5-pro` (via OAuth).
- Stranger Reply: Verified as configured via `TELEGRAM_STRANGER_REPLY`.
