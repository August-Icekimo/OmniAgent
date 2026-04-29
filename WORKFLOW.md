# OmniAgent Workflow — Multi-Agent Spec-Driven Development

> Single source of truth for **how work flows through OmniAgent**, from idea to archived feature.
> This document is canonical. AGENT.md §6/§7/§7.5 enforce the rules; this file explains the *play*.
> Last updated: 2026-04-29

---

## 1. Why This Document Exists

OmniAgent is built by **one human (Icekimo) + multiple AI agents** with overlapping but non-identical
capabilities. Without an explicit playbook:

- The same task gets started in three places and finished nowhere
- Spec-quality drifts because each agent picks its favourite format
- WIP discipline collapses the moment an agent doesn't know what's already in flight
- Decisions made in one channel (chat, IDE, terminal) never reach the others

This document defines **who does what, when, and where the artefact lives** at every stage.
It is the answer to the question: *"I have an idea — what's the next concrete step?"*

---

## 2. Cast & Capabilities

| Agent | Surface | Has codebase access? | Best at | Avoid using for |
|---|---|---|---|---|
| **Icekimo** | Brain | Always | Vision, taste, final calls, SOUL.md ownership | Mechanical grunt work |
| **Claude Opus 4.7** (WebUI) | Chat | ❌ No | High-level shaping, critique, long-form drafting | Anything requiring real file paths or live code |
| **Claude Code** (Antigravity / Pro) | Terminal + IDE | ✅ Yes | Interview-style grooming, spec authoring against real code, edge-case probing | Open-ended brainstorming (codebase frames thinking too early) |
| **Antigravity IDE** | Local IDE + QA | ✅ Yes (full local env) | Local testing, real-environment validation | Implementation (delegate to Jules) |
| **Jules** (Google) | Cloud coding agent | ✅ Yes (read+write) | Pure implementation against a finalised `tasks.md` | Anything requiring tests, live env, or design choices |
| **conv2spec** family of skills | Tooling | n/a | Compressing messy chat into structured Markdown | Anything requiring novel reasoning |

**Core principle of role assignment**:
> *No agent does work outside its strength zone, even if it technically can.*
> WebUI Opus *can* draft tasks.md, but it'll drift from real paths. Jules *can* propose designs,
> but the result won't reflect taste. Stay in lane.

---

## 3. The Pipeline (Bird's-Eye View)

```
┌─────────┐ Opus    ┌──────────┐  Claude Code   ┌─────────┐    /opsx:plan
│ Spark   │ ──────▶ │  Idea    │ ──────────────▶│  Ready  │ ──────────────▶ Sprint
│ (chat)  │ capture │ (sleeps) │   /opsx:explore│ (groomed)│
└─────────┘         └──────────┘                 └─────────┘
                                                      │
                                                      ▼ /opsx:propose
                                              ┌────────────────┐
                                              │ Active Change  │  proposal+design+tasks
                                              │ (WIP=1)        │  + spec.md delta
                                              └────────────────┘
                                                      │
                                                      ▼ Jules implements
                                                      ▼ Antigravity tests
                                                      ▼ Icekimo merges
                                                      │
                                                      ▼ /opsx:archive
                                              ┌────────────────┐
                                              │ Archived       │  spec.md synced
                                              │ + sprint row   │  ready/ card removed
                                              └────────────────┘
```

Five named stages: **Incubation → Grooming → Shaping → Implementation → Closure**.
Each stage has one or two agents in the lead, a defined entry condition, and a defined output.

---

## 4. Stage 1 — Incubation (WebUI Opus)

**Goal**: Take a vague spark and shape it into a defensible idea worth capturing.

**Lead agent**: Claude Opus 4.7 in WebUI.
**Why Opus, not Claude Code**: Codebase access at this stage is a liability — it constrains
imagination before the idea has earned its right to exist.

### What happens

1. Icekimo brings a problem, hunch, or constraint to WebUI Opus
2. Opus pushes back, surfaces blind spots, offers framings, links to long-term direction
3. Conversation converges on: *what hurts*, *who hurts*, *what would resolve it*
4. **Output**: a single `ideas2SlugMD` invocation that produces a draft `ideas/<slug>.md`

### Hard rules

- **No `/opsx:propose` from Stage 1.** If you find yourself wanting to write tasks.md here, stop —
  you're skipping Grooming.
- **No commits from Stage 1.** WebUI Opus produces text; Icekimo (or Claude Code) commits.
- **Only required fields**: `slug`, `domain`, `Why`, `What`. Acceptance hints stay empty.
  Open questions are *encouraged* — they signal honest uncertainty.

### Entry condition
A spark exists. That's it.

### Exit condition
A markdown blob ready to be saved as `openspec/backlog/ideas/<slug>.md`.

### Cooldown rule
**Captured ideas should sleep for at least 24 hours before being groomed.**
This kills 30%+ of ideas that felt brilliant at midnight. The backlog is for compounding signal,
not catching every flicker.

---

## 5. Stage 2 — Grooming (Claude Code in Antigravity)

**Goal**: Confront the idea with reality. Make it survive contact with the actual codebase.

**Lead agent**: Claude Code inside Antigravity.
**Why Claude Code, not Opus**: This stage requires reading `specs/<domain>/spec.md` and the
codebase to verify the idea isn't already covered, doesn't conflict with existing requirements,
and can be expressed in terms of real components.

### What happens

1. Icekimo runs `/opsx:explore <slug>` in Antigravity terminal
2. Claude Code reads `ideas/<slug>.md`, the relevant `specs/<domain>/spec.md`, and 2–3 source
   files in the affected domain
3. Claude Code conducts an **interview** with Icekimo, asking sharp questions like:
   - "This touches `memory` and `identity`. Which is the primary domain?"
   - "Existing `specs/security/spec.md` has Privacy in Logging. Your idea overlaps — `ADDED` or `MODIFIED`?"
   - "Acceptance hint #3 implies a DB column. Do you want a migration in this change?"
4. Open questions get resolved or explicitly marked unresolvable-this-iteration
5. **Output**: `ideas/<slug>.md` is `git mv`'d to `ready/<slug>.md`, with frontmatter `status: ready`,
   `Acceptance hints` ≥1 item, `Open questions` empty

### Hard rules

- `ready/` cards MUST have empty `Open questions`. If something's unresolved, it stays in `ideas/`.
- **No spec.md edits in this stage.** Only the backlog card moves.
- If grooming reveals the idea is actually 2+ ideas, **split the card** before moving to ready.
- If grooming reveals the idea is duplicate of an existing card, **merge and `git rm` the loser**.

### Entry condition
A non-trivial `ideas/<slug>.md` exists and has slept for ≥24 hours.

### Exit condition
A `ready/<slug>.md` ready to be picked into a sprint. Or the card is killed (`git rm`) — that's
also a valid outcome.

---

## 6. Stage 3 — Shaping (WebUI Opus + Claude Code in tandem)

**Goal**: Convert a ready card into a complete OpenSpec change set: `proposal.md`, optional
`design.md`, `tasks.md`, and the `spec.md` delta.

**Lead agents**: WebUI Opus drafts; Claude Code formalises and aligns to OpenSpec format.
**Why both**: Drafting needs vision and prose. Formalisation needs file-system truth.
Neither agent does this stage well alone.

### What happens

#### 3a. Sprint admission
Run `/opsx:plan` to open a 2-week sprint and select Committed/Stretch cards from `ready/`.
Without sprint membership, no card can be proposed.

#### 3b. Drafting (WebUI Opus)
Icekimo opens a WebUI conversation with Opus, attaches the relevant `ready/<slug>.md` and the
target `specs/<domain>/spec.md`, and runs the **`proposeSlug`** skill.

The skill produces three drafts:
- `proposal.md` (Why + What Changes + Capabilities + Impact)
- `design.md` (How — only if the change has architectural decisions)
- `spec.md` delta block (`## ADDED Requirements` or `## MODIFIED Requirements`)

`tasks.md` is NOT drafted in WebUI — it requires real path knowledge.

#### 3c. Formalisation (Claude Code in Antigravity)
Icekimo runs `/opsx:propose <slug>` in Antigravity. Claude Code:
1. Reads the WebUI drafts (Icekimo pastes them or saves them in a scratch location)
2. Validates against OpenSpec schema (`openspec instructions <artifact-id> --change <slug> --json`)
3. Writes `changes/<slug>/proposal.md`, `changes/<slug>/design.md`, `changes/<slug>/tasks.md`
4. Authors `tasks.md` with real file paths grounded in the codebase
5. **Inserts `0.1 Icekimo sign-off spec delta` as the first task** (mandatory SDD gate)

#### 3d. Sign-off (Icekimo)
Icekimo reviews the spec delta in `proposal.md` (or wherever the change schema places it),
checks `[x] 0.1` in tasks.md. **Until 0.1 is checked, Jules is forbidden to start.**

### Hard rules

- **Spec delta is truth.** Once 0.1 is signed off, that delta is binding. Changing it requires
  a new commit and explicit re-approval.
- **WIP=1 is enforced at `/opsx:propose`**, not at draft time. Drafting in WebUI for multiple
  cards in parallel is fine; only one can become an active change.
- **`tasks.md` task 0.1 is non-negotiable.** Do not let any agent skip it.

### Entry condition
A `ready/<slug>.md` is in the current sprint's Committed table.

### Exit condition
`changes/<slug>/` exists with all required artifacts, task 0.1 is signed off, Jules can begin.

---

## 7. Stage 4 — Implementation (Jules + Antigravity)

**Goal**: Turn `tasks.md` into working code that passes acceptance criteria.

**Lead agents**: Jules implements; Antigravity tests.
**Why this split**: Jules is fast and disciplined at pure implementation but must not run tests
or touch live environments. Antigravity has the real HomeLab access needed for validation.

### What happens

1. Jules reads `tasks.md` from task 1.1 onward (skipping 0.1, which is Icekimo's)
2. For each task, Jules writes code, opens a PR, ticks `[x]` on acceptance criteria
3. Antigravity pulls the PR, runs the verification steps in `tasks.md`, reports back
4. Icekimo reviews PR, merges (or sends back with comments)
5. Repeat until every task in `tasks.md` is `[x]`

### Hard rules

- **Jules MUST NOT modify `proposal.md`, `design.md`, or `specs/<domain>/spec.md`** during
  implementation. If Jules discovers the spec is wrong, it raises an issue and stops — Icekimo
  decides whether to re-shape or push through.
- **Antigravity MUST NOT implement.** It tests. Mixing roles destroys auditability.
- **PRs do not auto-merge.** Icekimo reviews every PR. This is HomeLab scale; speed is not the constraint, quality is.

### Entry condition
`tasks.md` task 0.1 is signed off.

### Exit condition
Every task in `tasks.md` is `[x]`. All PRs merged.

---

## 8. Stage 5 — Closure (`/opsx:archive`)

**Goal**: Move the change to history, sync the spec, clean up.

**Lead agent**: Claude Code in Antigravity (mechanical step).

### What happens

1. Icekimo runs `/opsx:archive <slug>`
2. Claude Code:
   - Validates all tasks are `[x]`
   - Syncs `spec.md` delta into `specs/<domain>/spec.md` (ADDED becomes part of the source of truth)
   - Moves `changes/<slug>/` to `changes/archive/YYYY-MM-DD-<slug>/`
   - `git rm openspec/backlog/ready/<slug>.md`
   - Annotates the sprint file's Committed table row with `(archived YYYY-MM-DD)`
3. Sprint becomes eligible for retro

### Hard rules

- **No archive without 100% task completion.** If a task is genuinely impossible, it must be
  removed from `tasks.md` with explicit Icekimo sign-off in the commit message.
- **Sprint retro must be filled before next `/opsx:plan`.** This is the rhythm gate.

### Entry condition
All tasks `[x]`, all PRs merged.

### Exit condition
Spec synced, change archived, ready card removed, sprint annotated.

---

## 9. Carry-over Rule (Reality Concession)

**Problem**: Jules and Antigravity work asynchronously. A change started in sprint W18 may not
finish before W18 closes.

**Rule**:
> When a sprint ends with an `active change`, write `Carry-over: <slug>` in the Retro section.
> The next sprint's Committed table MUST list the same `<slug>` first, annotated `(carry-over)`.
> WIP=1 still applies — no new `/opsx:propose` until the carry-over is archived.

This concession preserves WIP=1 (the discipline that matters) while admitting calendar reality.

---

## 10. Where Each Artifact Lives

| Artifact | Path | Authored by | Owns truth? |
|---|---|---|---|
| Spark / chat | (ephemeral) | Icekimo + Opus | No |
| Idea card | `openspec/backlog/ideas/<slug>.md` | `ideas2SlugMD` skill | No (capture) |
| Ready card | `openspec/backlog/ready/<slug>.md` | Claude Code via `/opsx:explore` | No (intent) |
| Sprint file | `openspec/backlog/sprints/<YYYY>-W<NN>.md` | `/opsx:plan` | No (commitment) |
| Proposal | `openspec/changes/<slug>/proposal.md` | Opus draft + Claude Code formalise | No (justification) |
| Design | `openspec/changes/<slug>/design.md` | Opus draft + Claude Code formalise | No (rationale) |
| Tasks | `openspec/changes/<slug>/tasks.md` | Claude Code | No (work plan) |
| Spec delta | inside proposal/design (per OpenSpec schema) | Opus draft, Icekimo signs | **Becomes truth on archive** |
| Code | `omni-agent/<service>/...` | Jules | No (implementation) |
| Spec (canonical) | `openspec/specs/<domain>/spec.md` | `/opsx:archive` syncs from delta | **YES — source of truth** |
| Sprint retro | `openspec/backlog/sprints/<YYYY>-W<NN>.md#Retro` | Icekimo manually | No (memory) |

**Rule of thumb**: Only `specs/<domain>/spec.md` after archive holds binding truth. Everything else
is intent, plan, or history.

---

## 11. The Skills Map

Three skills support the pipeline. They share a naming convention: `<verb><Object>`.

| Skill | Stage | Input | Output | Surface |
|---|---|---|---|---|
| `ideas2SlugMD` | 1 (Incubation) | Conversation context | `ideas/<slug>.md` markdown blob | WebUI Opus |
| `proposeSlug` | 3 (Shaping, drafting half) | A `ready/<slug>.md` + relevant `spec.md` | `proposal.md` + optional `design.md` + spec delta block | WebUI Opus |
| `conv2spec` (legacy) | (deprecated for OpenSpec) | Long conversation | Standalone spec MD | WebUI Opus |

`conv2spec` is **kept** for one-off non-OpenSpec work (e.g. drafting a SOUL.md amendment, writing
a one-page architecture doc). It is **not** used inside the OpenSpec pipeline anymore.

---

## 12. Anti-Patterns (Things That Will Break the Flow)

| Anti-pattern | Why it breaks | What to do instead |
|---|---|---|
| Drafting `tasks.md` in WebUI | Paths drift from real codebase; Jules struggles | Draft `proposal.md` in WebUI, let Claude Code author `tasks.md` |
| Skipping `/opsx:explore` to save time | Idea hits propose stage half-formed; spec delta is shallow | Always groom; the 24h sleep + interview is what makes the spec defensible |
| Using `--force` to override WIP=1 | There is no `--force`. By design. | Archive the current change first, or kill it explicitly |
| Letting Jules edit spec.md | Spec is truth; truth must be human-approved | Jules raises an issue, Icekimo re-shapes |
| Filling retro retroactively while planning | Retro becomes theatre, not learning | Block on missing retro; the gate exists for a reason |
| Capturing every spark immediately | Backlog drowns in noise | Sleep first, capture only what survives 24h |
| Multiple WebUI conversations spawning competing drafts | Drift, conflict, wasted token budget | One ready card → one drafting session → one `/opsx:propose` |

---

## 13. Daily / Weekly / Sprint Rhythm

| Cadence | Activity | Surface |
|---|---|---|
| Daily | Capture sparks (if any) | WebUI Opus → `/opsx:capture` |
| Mid-week | Groom 1–2 ideas | Antigravity Claude Code → `/opsx:explore` |
| Sprint start (Mon W odd) | `/opsx:plan` | Antigravity Claude Code |
| Sprint week 1 | Shape and propose 1 change | WebUI Opus → Antigravity |
| Sprint week 2 | Implementation finishes, archive | Jules + Antigravity → `/opsx:archive` |
| Sprint end (Sun W even) | Fill Retro section manually | Icekimo |

This is aspirational. Reality will deviate. The carry-over rule (§9) absorbs that.

---

## 14. Glossary

| Term | Meaning |
|---|---|
| **Spark** | A pre-idea thought, not yet captured |
| **Idea** | A captured thought sitting in `ideas/` |
| **Ready card** | A groomed idea with empty open questions, sitting in `ready/` |
| **Sprint** | A 2-week ISO-week-aligned commitment window |
| **Change** | An active OpenSpec change set in `changes/<slug>/` |
| **Spec delta** | The `ADDED`/`MODIFIED` block that updates a domain spec on archive |
| **Domain** | One of the 8: brain, gateway, identity, llm, memory, security, skills, soul |
| **WIP=1** | At most one active change at any time. No exceptions, no flags. |
| **Carry-over** | A slug that survives a sprint boundary; preserves WIP=1 across sprints |

---

## 15. Open Questions for Future Workflow Iterations

> These are deliberate gaps. Address when the workflow has been used for ≥3 sprints.

- Should there be an `/opsx:retro` command to formalise retro filling?
- Should a 9th `tooling` / `meta` domain exist for opsx command upkeep?
- How do we handle a Phase-spanning theme that needs 3+ changes? (Currently each is independent;
  no explicit "epic" container exists.)
- When does WebUI Opus's draft get archived? Currently it lives in chat history only.

---

## 16. Document Maintenance

This file is updated when:
- A new agent joins the cast (§2 table grows)
- A workflow stage is added or removed (§3–§8 changes)
- A new skill is added to the pipeline (§11)
- A new anti-pattern is identified after a real bad sprint (§12)

Updates are committed with message format: `docs(workflow): <one-line summary>`.

Three-way command parity (§7.5 of AGENT.md) does NOT apply here — this is single-source
human-readable documentation, not a command definition.
