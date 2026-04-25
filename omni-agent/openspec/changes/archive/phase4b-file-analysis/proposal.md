## Why

To enable Omni-Agent to receive and analyze files (PDF, Images, Excel) sent via Telegram, and to modernize the Wake-on-LAN (WoL) system by moving target management from manual input to a database-backed registry. It also establishes a shared workspace for file processing with automated cleanup.

## What Changes

- `gateway/`: Added file download logic for Telegram and `Attachment` metadata in `StandardMessage`.
- `brain/`: New `FileAnalyzer` skill using `pypdf`, `pandas`, and Claude Vision. Added a background task for workspace cleanup.
- `skills/`: Updated WoL handler to lookup MAC addresses in the `wol_targets` table.
- `db/migrations/`: Added `004_wol_targets_workspace.sql`.
- `compose.yml`: Added a shared `omni-workspace` volume.

## Capabilities

### Modified Capabilities
- `gateway`: Support for receiving and downloading Telegram attachments.
- `skills`: Enhanced `wake_on_lan` with DB-backed target lookup; new `file_analyze` skill.
- `brain`: Ability to interpret and summarize document and image content.

## Impact

- Users can send files for analysis.
- WoL can be triggered using semantic names (e.g., "Wake up workstation").
- Files are automatically deleted from the workspace after 120 hours of inactivity.

## Open Questions

- Excel Multi-Sheet: Handled by concatenating sheet content (limited to 5 sheets recommended).
- WoL Matching: Uses semantic matching in the planner node.
