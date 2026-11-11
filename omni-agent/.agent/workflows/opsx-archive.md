---
description: Archive a completed change in the experimental workflow
---

Archive a completed change.

**Input**: optional change name (e.g. `/opsx:archive add-auth`). If omitted, run `openspec list --json`, show active changes, and let the user choose. **Never auto-select.**

**Steps**

1. **Artifacts** — `openspec status --change "<name>" --json`. If any artifact isn't `done`, warn and ask to continue.
2. **Tasks** — count `- [ ]` vs `- [x]` in the tasks file. If incomplete, warn and ask to continue. No tasks file → skip.
3. **Delta specs** — if `openspec/changes/<name>/specs/` exists, compare each with `openspec/specs/<capability>/spec.md`, show one combined summary of adds/modifications/removals/renames, then ask:
   - changes needed: "Sync now (recommended)" / "Archive without syncing"
   - already synced: "Archive now" / "Sync anyway" / "Cancel"
   On sync, merge the deltas into the main specs before moving.
4. **Move** — target `openspec/changes/archive/YYYY-MM-DD-<name>` (today's date). If it already exists, stop and report. Otherwise:
   ```bash
   mkdir -p openspec/changes/archive
   mv openspec/changes/<name> openspec/changes/archive/YYYY-MM-DD-<name>
   ```
   (`.openspec.yaml` moves with the directory.)
5. **Ready card & sprint**
   - If `openspec/backlog/ready/<name>.md` exists → `git rm` it. If not, continue silently (legacy/manual change).
   - In the active sprint file (latest `openspec/backlog/sprints/<YYYY>-W<NN>.md`), find this slug in `Committed` and append `(archived YYYY-MM-DD)` to its `OpenSpec change` column.
6. **Summary** — change, schema, archive path, spec sync status (synced / skipped / no delta specs), ready-card removal, and any warnings accepted.

Warnings never block; inform and confirm.
