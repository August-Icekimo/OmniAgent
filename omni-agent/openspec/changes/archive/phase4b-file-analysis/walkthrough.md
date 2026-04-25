# Walkthrough - Phase 4B: File Analysis & WoL Target Registry

I have successfully implemented Phase 4B, enabling file analysis, database-backed WoL management, and automated workspace maintenance.

## Changes Made

### 1. Database & Infrastructure
- **DB Migration**: Added `004_wol_targets_workspace.sql` to manage WoL targets and workspace file logs.
- **Compose**: Added a shared named volume `omni-workspace` mounted at `/workspace` in both `gateway` and `brain` containers.

### 2. Gateway Enhancements
- **File Receipt**: Updated Telegram handler to support `document` and `photo` updates.
- **Download Logic**: Implemented synchronous download with a 10MB size limit and 4s timeout.
- **Workspace Integration**: Files are saved to `/workspace/uploads/{user_id}/` and logged in the DB.

### 3. Brain & AI Analysis
- **FileAnalyzer Skill**: Created `brain/skills/file_analyzer.py` supporting:
  - **PDF**: Text extraction via `pypdf`.
  - **Images**: OCR and description via Claude Vision API.
  - **Excel/CSV**: Structured reading via `pandas`.
- **LangGraph Routing**: `planner_node` now automatically routes messages with attachments to the `FileAnalyzer` skill.
- **Workspace Cleanup**: Added a background task in `brain/agent/proactive.py` to delete files older than 120 hours.

### 4. Skills Server
- **DB Integration**: Added PostgreSQL connection pool to the Go Skills server.
- **WoL Registry**: Updated `HandleWOL` to lookup MAC addresses by `target_name` (AI name or label) in the database, while remaining backward compatible with direct MAC inputs.

## Verification Results

### Build Status
- **Gateway**: `go build` successful.
- **Skills**: `go build` successful (after adding `pgx` dependency).
- **Brain**: `requirements.txt` updated with new analysis dependencies.

### Manual Verification Steps (For User)
1. **Apply Migration**: Ensure the database is updated with the new schema.
2. **Restart Services**: Run `podman compose up --build -d` to apply volume and code changes.
3. **Register WoL Target**:
   ```sql
   INSERT INTO wol_targets (mac, ai_name, label) VALUES ('AA:BB:CC:DD:EE:FF', '我的電腦', 'workstation');
   ```
4. **Test WoL**: Tell Cindy "叫醒我的電腦" and check logs.
5. **Test File Analysis**: Send a PDF, image, or Excel file to Cindy and verify her response.
