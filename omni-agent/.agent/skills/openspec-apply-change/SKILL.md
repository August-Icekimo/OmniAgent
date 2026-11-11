---
name: openspec-apply-change
description: Implement tasks from an OpenSpec change. Use when the user wants to start implementing, continue implementation, or work through tasks.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.3.1"
---

Implement tasks from an OpenSpec change.

**Input**: optional change name (e.g. `/opsx:apply add-auth`). If omitted, infer from conversation or auto-select when only one active change exists; otherwise run `openspec list --json` and ask. Announce "Using change: <name>".

**Steps**

1. `openspec status --change "<name>" --json` — note `schemaName` and which artifact holds tasks.
2. `openspec instructions apply --change "<name>" --json` — returns `contextFiles`, progress, task list, dynamic instruction.
   - `state: "blocked"` (missing artifacts) → say so, suggest `/opsx:propose`.
   - `state: "all_done"` → suggest `/opsx:archive`.
3. Read every file under `contextFiles` (don't assume file names). Show "N/M tasks complete" and remaining tasks.
4. For each pending task: implement minimal, scoped changes → mark `- [ ]` → `- [x]` in the tasks file **immediately** → next task.

**Pause and ask the user when:**
- A DB schema / migration change is needed
- A new package or dependency is needed
- `brain/config/routing_config.json` provider settings would change
- A task is unclear, or implementation shows a design assumption is wrong (suggest updating the artifacts; not phase-locked)
- An error or blocker occurs — report it, don't guess

On finish or pause: list tasks completed this session, overall progress, and next step.
