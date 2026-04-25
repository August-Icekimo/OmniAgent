# Implementation Plan - Phase 4B: File Analysis & WoL Target Registry

This phase introduces file receipt and analysis capabilities, transitions WoL management to a database-backed registry, and implements a shared workspace for file processing with automatic cleanup.

## User Review Required

> [!IMPORTANT]
> **Shared Workspace Volume**: A new volume `omni-workspace` will be added to `compose.yml`. This requires a restart of the containers.
> **Telegram Bot Permissions**: Ensure the Telegram Bot has permissions to download files (default for standard bots).
> **API Keys**: Claude Vision requires `ANTHROPIC_API_KEY`. Ensure it is set in `.env`.

## Proposed Changes

### Database Layer

#### [NEW] [004_wol_targets_workspace.sql](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/db/migrations/004_wol_targets_workspace.sql)
- Create `wol_targets` table for MAC address management.
- Create `file_workspace_log` table for file access tracking and cleanup.

---

### Gateway Component

#### [MODIFY] [standard_message.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/gateway/internal/model/standard_message.go)
- Add `Attachment` struct.
- Add `Attachment` field to `StandardMessage`.

#### [MODIFY] [telegram.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/gateway/internal/handler/telegram.go)
- Update `telegramUpdate` to include `Document` and `Photo` details.
- Implement file download logic with a 10MB soft limit and 4s timeout.
- Save files to `/workspace/uploads/{user_id}/`.
- Insert record into `file_workspace_log` upon successful download.

---

### Brain Component

#### [MODIFY] [main.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/main.py)
- Add `AttachmentModel` and update `StandardMessage` Pydantic model.
- Update `chat` endpoint to pass attachment info to the agent graph.

#### [MODIFY] [graph.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/graph.py)
- Update `AgentState` to include `attachment`.
- Modify `planner_node` to detect attachments and route to `file_analyze` skill, bypassing confirmation.

#### [NEW] [file_analyzer.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/skills/file_analyzer.py)
- Implement `FileAnalyzer` class.
- Support PDF (using `pypdf`), Images (using Claude Vision API via `ModelRouter`), and Excel (using `pandas` + `openpyxl`).
- Update `file_workspace_log.last_accessed_at` on file access.

#### [MODIFY] [proactive.py](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/agent/proactive.py)
- Add `workspace_cleanup_task` that runs every hour.
- Delete files and DB logs older than 120 hours (5 days).

#### [MODIFY] [requirements.txt](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/brain/requirements.txt)
- Add `pypdf`, `openpyxl`, `pandas`.

---

### Skills Component

#### [MODIFY] [main.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/skills/main.go)
- Initialize a PostgreSQL connection pool on startup using `POSTGRES_*` env vars.
- Pass the DB pool to handlers that need it.

#### [MODIFY] [wol.go](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/skills/handler/wol.go)
- Update `HandleWOL` to accept `target_name`.
- Lookup MAC address in `wol_targets` if `mac` is not directly provided.

---

### Infrastructure

#### [MODIFY] [compose.yml](file:///home/icekimo/gitWrk/OmniAgent/omni-agent/compose.yml)
- Define `omni-workspace` volume.
- Mount volume to `gateway` and `brain` at `/workspace`.

## Verification Plan

### Automated Tests
- Run `podman compose up --build` to ensure all services start and dependencies are installed.
- Verify DB migrations are applied.

### Manual Verification
1. **WoL Registry**:
   - Insert a test record: `INSERT INTO wol_targets (mac, ai_name, label) VALUES ('AA:BB:CC:DD:EE:FF', '工作站', 'workstation');`
   - Ask Cindy: "叫醒工作站"
   - Check Skills log for successful MAC lookup and packet send.
2. **File Analysis**:
   - Send a PDF to the Telegram bot.
   - Verify it is downloaded to `/workspace`.
   - Verify Cindy provides a summary.
   - Repeat for an image (OCR) and an Excel file.
3. **Workspace Cleanup**:
   - Manually set a `file_workspace_log` entry to 121 hours ago.
   - Verify the file is deleted by the background task.
4. **Size Limit**:
   - Send a >10MB file.
   - Verify Cindy replies with the limit warning and doesn't download.
