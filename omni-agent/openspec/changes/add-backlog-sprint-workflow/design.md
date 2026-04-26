# Implementation Plan — Add Backlog & Sprint Workflow

This change introduces a lightweight Agile backlog and sprint layer on top of the existing OpenSpec workflow. It adds the `openspec/backlog/` directory tree, two new agent commands (`/opsx:capture` and `/opsx:plan`), updates to three existing commands (`propose`, `archive`, `plan-coupling-on-propose`), and updates to `AGENT.md` to make the new rules canonical.

## User Review Required

> [!IMPORTANT]
> **WIP=1 hard limit**: After this change, `/opsx:propose` will refuse to create a new change if any active change exists. To start a new change, the previous one must be archived first. There is no `--force` override.
> **Sprint retro gating**: `/opsx:plan` will refuse to open a new sprint if the previous sprint file lacks a populated `Retro` section. Retro is filled manually in the sprint file (no `/opsx:retro` command in this iteration).
> **ROADMAP.md 已 seed**: 本 change 直接寫入 Phase 5 (Family Preference Awareness) 與 Phase 6 (AAAK Memory Compression) 主題，套用後即可作為第一次 sprint planning 的依據。Q4+ 主題待 Phase 5 結束後依進度補入。
> **Three-way command parity**: All command changes happen across `.agent/`, `.gemini/`, and `.claude/` simultaneously. PRs that update only one set must be rejected.

## Proposed Changes

---

### 1. Directory Structure

#### [NEW] `openspec/backlog/`

Tree to create:

```
openspec/backlog/
├── ROADMAP.md
├── _templates/
│   ├── item.md
│   └── sprint.md
├── ideas/
│   └── .gitkeep
├── ready/
│   └── .gitkeep
└── sprints/
    ├── .gitkeep
    └── archive/
        └── .gitkeep
```

The `_templates/` directory is a single source of truth for both `ideas/` and `ready/` items (same template, different `Status:` field) and for sprint files.

---

### 2. Backlog Item Template

#### [NEW] `openspec/backlog/_templates/item.md`

Format used by both `ideas/<slug>.md` and `ready/<slug>.md`:

```markdown
---
slug: <kebab-case-slug>
status: idea | ready | in-sprint | in-progress | done
domain: brain | gateway | identity | llm | memory | security | skills | soul
size: XS | S | M | L
priority: P0 | P1 | P2
created: YYYY-MM-DD
---

# <Slug Title in Human Words>

## Why
<2-3 lines: the pain point, who it affects>

## What (high-level)
<What we want to achieve, no implementation>

## Acceptance hints
- <draft AC, may be rough; required only for ready/>

## Open questions
- <unresolved items; MUST be empty for ready/>

## Links
- Roadmap: openspec/backlog/ROADMAP.md#<anchor>
- Related spec: openspec/specs/<domain>/spec.md
- Depends on: <other-slug>
```

**Validation rules:**
- All items: `slug`, `status`, `domain`, `Why`, `What` are mandatory
- `domain` MUST be one of the 8 OpenSpec domains; any other value is a validation error
- `ideas/` items: `Acceptance hints` and `Open questions` may be empty
- `ready/` items: `Open questions` MUST be empty (or absent); `Acceptance hints` MUST have ≥1 item

---

### 3. Sprint Template

#### [NEW] `openspec/backlog/_templates/sprint.md`

```markdown
---
sprint: <YYYY>-W<NN>
window_start: YYYY-MM-DD
window_end: YYYY-MM-DD
status: active | closed
---

# Sprint <YYYY>-W<NN>

**Window**: <YYYY-MM-DD> → <YYYY-MM-DD> (2 weeks)
**Theme**: <one-line objective for this sprint>
**Capacity**: <e.g. evenings + weekends ≈ 20h>

## Goals
1. <Sprint goal 1>
2. <Sprint goal 2>

## Committed
| Slug | Domain | Size | OpenSpec change | Owner |
|------|--------|------|-----------------|-------|
| <slug> | <domain> | <size> | (filled when /opsx:propose runs) | Jules / Antigravity |

## Stretch
| Slug | Reason |
|------|--------|
| <slug> | <why this is stretch and not committed> |

## Out of scope
- <explicitly excluded item>

## Retro
<!-- Filled at sprint end. /opsx:plan will refuse to start a new sprint
     if this section is empty for the previous sprint. -->

### What worked
- 

### What didn't
- 

### Carry-over
- <slug> → reason
```

**Filename**: `<YYYY>-W<NN>.md` where `<NN>` is ISO week number with leading zero (e.g. `2026-W17.md`).

**ISO year handling**: When the 2-week window crosses a year boundary, use the ISO year that contains the **start** Monday.

---

### 4. ROADMAP.md

#### [NEW] `openspec/backlog/ROADMAP.md`

```markdown
# OmniAgent Roadmap

> Quarterly themes that guide backlog grooming.
> Update at start of each quarter.

## 2026 Q2 — Phase 5: Family Preference Awareness
**Theme**: Cindy 認得家人，並能依不同傳輸 channel 套用個人化的偏好與隱私設定。

Candidate epics:
- 家庭成員偏好資料模型 (`user_preferences` 表 + 跨平台繼承規則)
  - Domain: `identity`, `memory`
  - 偏好類型：稱呼、回覆語氣、推播時段、敏感話題黑名單
- Per-channel 偏好套用機制
  - Domain: `gateway`, `brain`
  - LINE/Telegram/BlueBubbles 各自的隱私顆粒度（例如 LINE 群組 vs 私訊）
- 偏好學習與顯式覆寫
  - Domain: `brain`, `memory`
  - Cindy 從互動中推斷偏好；家人可用自然語言主動修正
- 隱私邊界規則
  - Domain: `security`, `identity`
  - 家人 A 的偏好/記憶絕不洩漏給家人 B；admin 例外規則

## 2026 Q3 — Phase 6: AAAK Memory Compression (research)
**Theme**: 用 Associative Array Augmented Kernel 把長期記憶壓縮為可注入 prompt 的「直覺片段」，靈感來自 MemPalace 記憶系統。

Candidate epics:
- AAAK 概念驗證（PoC）
  - Domain: `memory`, `llm`
  - 設計聯想鍵（associative key）的擷取與索引；初版可用 embedding cluster centroid
- 直覺提示字（intuition snippet）注入機制
  - Domain: `brain`, `llm`
  - System prompt 中保留專屬區塊；token budget 與 routing 整合
- 記憶壓縮率與召回品質量測
  - Domain: `memory`
  - 對照組：原始記憶 vs AAAK 壓縮版的回覆品質差異
- 與既有 memory 系統的共存策略
  - Domain: `memory`, `brain`
  - AAAK 是 augment 不是 replace；兩層查詢的優先順序

## 2026 Q4 — TBD
**Theme**: 待 Phase 5 Q2 結束後依進度與發現的需求重新規劃。

Candidate epics:
- (留白，根據 Phase 5/6 retro 補入)

---

## Long-term Direction

OmniAgent 的長期方向有兩條主軸：

1. **People-centric awareness**: 從「Cindy 認得帳號」進化到「Cindy 認得人，且記得每個人在不同情境下的樣子」。Phase 4 的 UUID 身分系統是地基；Phase 5 的偏好系統是第一層；後續可能延伸到家人情緒辨識、家庭事件記憶（生日、紀念日、習慣作息）。

2. **Memory as native cognition**: 從「Cindy 查詢資料庫」進化到「Cindy 直覺地知道」。Phase 6 的 AAAK 是這條主軸的開端。長期目標是讓 Cindy 的記憶系統不只是 RAG，而是更接近人類記憶的聯想式、壓縮式、可融入 system prompt 的結構。MemPalace 是重要參考。

兩條主軸交會處：當家人偏好被壓縮成 AAAK 直覺片段時，Cindy 不需要每次查 DB 就「知道」要怎麼跟誰說話。這是長期願景。
```

**Note**: 上方 ROADMAP 內容由 Icekimo 在 spec 撰寫階段提供。Phase 5/6 主題已定，Q4+ 由後續 sprint retro 結果驅動補入。

---

### 5. New Command: `/opsx:capture`

#### [NEW] `.agent/workflows/opsx-capture.md`

Behavior:

1. Parse arguments: `[<free-text-description>] [--domain <d>] [--why <text>] [--what <text>]`
2. Derive a kebab-case slug from the description (or first non-flag argument)
3. Check for slug collision in `openspec/backlog/ideas/`, `ready/`, and active sprint files. If collision: abort with suggestions
4. For each missing required field (`why`, `what`, `domain`), use AskUserQuestion to elicit
5. Validate `domain` against the 8-domain list; on mismatch, re-prompt
6. Write `openspec/backlog/ideas/<slug>.md` from `_templates/item.md`, populating frontmatter (`status: idea`, `created: <today>`) and body fields
7. Print confirmation: relative path + 1-line summary

**Exit codes**: 0 success, 1 user-cancelled, 2 validation error, 3 collision

**CLI flag examples**:
```bash
/opsx:capture wol-targets --domain skills --why "Manual MAC entry is error-prone" --what "DB-backed WoL target registry with semantic names"
# Non-interactive when all required fields supplied via flags
```

#### [NEW] `.gemini/commands/opsx/capture.toml`

```toml
description = "Capture an idea into openspec/backlog/ideas/"

prompt = """
Capture a new idea into the backlog.

[same step body as the .agent version, formatted as Gemini prompt]
"""
```

#### [NEW] `.claude/commands/opsx-capture.md`

Same step body, formatted for Claude Code conventions (no TodoWrite reference; uses inline tool calls).

#### [NEW] `.agent/skills/openspec-capture/SKILL.md` and `.gemini/skills/openspec-capture/SKILL.md`

YAML frontmatter following existing pattern:

```yaml
---
name: openspec-capture
description: Capture a new idea into openspec/backlog/ideas/. Use when the user wants to record a feature idea, bug fix concept, or improvement thought without committing to implementation timing.
license: MIT
compatibility: Requires openspec backlog directory structure.
metadata:
  author: omni-agent
  version: "1.0"
---
```

Body mirrors workflow file step list.

---

### 6. New Command: `/opsx:plan`

#### [NEW] `.agent/workflows/opsx-plan.md`

Behavior:

1. **Gate: previous sprint must have retro filled**. List `openspec/backlog/sprints/*.md` (excluding `archive/`). If a non-empty file exists with `status: active` in frontmatter or with empty Retro section, abort with: "Previous sprint <YYYY-W<NN>> has no retro. Fill Retro section then run again."
2. **Compute current ISO week**: Use system time (`date +%G-W%V`). If `openspec/backlog/sprints/<YYYY>-W<NN>.md` already exists, abort with existing path
3. **Read ready cards**: Scan `openspec/backlog/ready/*.md`. If empty, abort: "No ready cards. Run /opsx:explore on ideas first."
4. **Ask user for goals**: Open-ended AskUserQuestion: "What is this sprint's main objective?" → goes into `Theme` and `Goals`
5. **Ask user to select committed cards**: Multi-select AskUserQuestion with all ready cards as options
6. **Ask user to select stretch cards**: Multi-select AskUserQuestion with remaining ready cards
7. **Ask user for out-of-scope (free text)**: optional, can be skipped
8. **Ask user for capacity hint**: free text (e.g. "evenings + weekends ≈ 20h")
9. **Compute window**: Start = Monday of current ISO week (or today if today is Monday); End = Start + 13 days
10. **Move previous sprint to archive**: If a closed previous sprint exists at `sprints/<YYYY-W<NN>>.md` (not in `archive/`), `git mv` it to `sprints/archive/`
11. **Write sprint file** at `openspec/backlog/sprints/<YYYY>-W<NN>.md` from template
12. **Update each committed card**: Set `status: in-sprint` in frontmatter
13. **Print summary**: sprint window, committed slug list, stretch slug list

**Exit codes**: 0 success, 1 user-cancelled, 2 previous sprint not retro'd, 3 no ready cards, 4 sprint already exists for this week

#### [NEW] `.gemini/commands/opsx/plan.toml`、`.claude/commands/opsx-plan.md`

Same body, format-adapted.

#### [NEW] `.agent/skills/openspec-plan/SKILL.md` and `.gemini/skills/openspec-plan/SKILL.md`

YAML frontmatter:

```yaml
---
name: openspec-plan
description: Open a new sprint by selecting cards from openspec/backlog/ready/ and writing a sprint plan. Use when the user wants to start a new 2-week iteration.
license: MIT
compatibility: Requires openspec backlog directory structure.
metadata:
  author: omni-agent
  version: "1.0"
---
```

---

### 7. Modified Command: `/opsx:propose`

#### [MODIFY] `.agent/workflows/opsx-propose.md`、`.gemini/commands/opsx/propose.toml`、`.claude/commands/opsx-propose.md`

Add two new pre-flight checks **before** `openspec new change` is called:

**Check A — WIP limit (hard)**:
```
Run: openspec list --json
Count: number of changes where archived=false (or whatever field indicates active)
If count >= 1:
  Abort with message:
    "WIP limit reached. Active change: <existing-slug>.
     Archive it first: /opsx:archive <existing-slug>
     No --force override is permitted (per AGENT.md §6)."
  Exit non-zero
```

**Check B — slug continuity from sprint**:
```
Find the active sprint file (latest <YYYY>-W<NN>.md not in archive/).
If none: abort with "No active sprint. Run /opsx:plan first."

Read its Committed and Stretch tables.
If proposed slug not in either:
  Abort: "Slug <slug> is not in current sprint <YYYY-W<NN>>.
          Either /opsx:capture + /opsx:plan first, or pick a slug from the sprint."
  Exit non-zero

If slug is in Stretch (not Committed):
  Confirm with user: "Slug is in Stretch tier — proceed anyway? (y/N)"
  If no: abort

If slug exists in ready/<slug>.md:
  After successful change creation, set ready/<slug>.md frontmatter status: in-progress
  Update sprint file's Committed table OpenSpec change column with the change name
```

Existing logic (running `openspec new change`, generating artifacts) stays unchanged.

---

### 8. Modified Command: `/opsx:archive`

#### [MODIFY] `.agent/workflows/opsx-archive.md`、`.gemini/commands/opsx/archive.toml`、`.claude/commands/opsx-archive.md`

After Step 5 (Perform the archive — moves change directory to `changes/archive/YYYY-MM-DD-<slug>/`), insert new Step 5.5:

```
**Step 5.5 - Remove ready card (Q1 decision: do not retain)**

Check if openspec/backlog/ready/<slug>.md exists.
If yes:
  git rm openspec/backlog/ready/<slug>.md
  Add to summary: "Removed ready card: openspec/backlog/ready/<slug>.md"
If no:
  Log debug: "No matching ready card to remove (likely a legacy/manual change)"
  Continue without warning

Update sprint file (find current sprint by ISO week of today):
  In Committed table, mark this slug's row with `(archived YYYY-MM-DD)` next to the change name.
```

**Note**: Following Q1 decision, completed ready cards are NOT moved to `done/` — they are deleted. Historical traceability is provided by `changes/archive/<date>-<slug>/` directories. The sprint file annotation gives sprint-level visibility of completed work.

---

### 9. AGENT.md Updates

#### [MODIFY] `omni-agent/AGENT.md`

**§6 Development Rules** — add new rule:

```markdown
- **WIP limit (hard).** Maximum 1 active OpenSpec change at any time.
  `/opsx:propose` MUST refuse if `openspec list --json` shows ≥1 active change.
  No `--force` override. To start a new change, archive the current one first.
```

**§7 OpenSpec Workflow → Workflow Commands table** — add two rows:

```markdown
| `capture` | Capture a new idea into openspec/backlog/ideas/. |
| `plan`    | Open a new sprint, select cards from ready/, produce sprint file. |
```

**§7.5 Backlog & Sprint Workflow** (NEW SECTION, inserted between current §7 and §8) — full text:

```markdown
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
```

**Section renumbering**: Current §8 (Cross-Workspace Map) becomes §8 unchanged (since §7.5 is a sub-section of 7, not a new top-level number). Verify all internal references stay valid.

---

### 10. Compatibility & Non-Functional

- **OpenSpec CLI**: All new content sits under `openspec/backlog/` which CLI ignores. `openspec list/status/instructions/validate` outputs unchanged.
- **Git history**: All file movements use `git mv` to preserve history. Deletions via `git rm` (per Q1).
- **Three-way command parity**: Any update to a command must touch all three sets (`.agent/`, `.gemini/`, `.claude/`). Documented in AGENT.md §7.5 last paragraph (TODO: also add to a CONTRIBUTING.md if it exists).
- **No runtime impact**: No changes to Brain, Gateway, Skills, DB, SOUL.md, runtime configs.
- **No CI changes**: pre-commit hook for Domain validation explicitly out of scope (Q4).
