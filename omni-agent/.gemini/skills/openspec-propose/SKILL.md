---
name: openspec-propose
description: Propose a new change with all artifacts generated in one step. Use when the user wants to quickly describe what they want to build and get a complete proposal with design, specs, and tasks ready for implementation.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.3.1"
---

Propose a new change: create it and generate all artifacts needed for implementation in one step.

**Input**: change name (kebab-case) or a description of what to build. If nothing given, ask what they want to build and derive a kebab-case slug. Don't proceed without understanding the goal.

**Steps**

1. **Gate A — WIP limit (hard).** `openspec list --json`; if ≥1 change has `archived: false`, abort: "WIP limit reached. Active change: `<slug>`. Archive it first: `/opsx:archive <slug>`. No `--force` override (AGENT.md §6)."
2. **Gate B — sprint membership.** Find the active sprint (latest `openspec/backlog/sprints/<YYYY>-W<NN>.md`, not in `archive/`). None → abort: "No active sprint. Run `/opsx:plan` first."
   - Slug not in `Committed` or `Stretch` → abort: "Slug `<slug>` is not in current sprint `<sprint>`. `/opsx:capture` + `/opsx:plan` first, or pick a slug from the sprint."
   - Slug only in `Stretch` → ask "proceed anyway? (y/N)"; abort on no.
   - If a change with that name already exists, ask whether to continue it.
3. **Create** — `openspec new change "<name>"`. Then:
   - `openspec/backlog/ready/<name>.md` exists → set frontmatter `status: in-progress`.
   - In the sprint file, set this slug's `OpenSpec change` column to `openspec/changes/<name>/`.
4. **Build artifacts** — `openspec status --change "<name>" --json` gives `applyRequires` and `artifacts`. Loop over artifacts whose dependencies are satisfied:
   - `openspec instructions <artifact-id> --change "<name>" --json` → `template`, `instruction`, `outputPath`, `dependencies`, `context`, `rules`.
   - Read completed dependencies, write the file at `outputPath` using `template` and `instruction`.
   - **`context` and `rules` are constraints for you — never copy them (or `<context>`/`<rules>`/`<project_context>` blocks) into the file.**
   - Re-run status; stop when every `applyRequires` artifact is `done`.
   - Ask only if context is critically unclear; otherwise make reasonable decisions.
5. `openspec status --change "<name>"`, summarize the artifacts created, and suggest `/opsx:apply`.
