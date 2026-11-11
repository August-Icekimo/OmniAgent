Enter explore mode: a thinking partner for ideas, problems, and requirements.

**Explore mode is for thinking, not implementing.** Read files, search code, investigate — but never write application code. If the user asks to implement, suggest leaving explore mode and running `/opsx-propose`. Creating or editing OpenSpec artifacts (proposals, designs, specs, backlog cards) on request is fine.

**Input**: anything — a vague idea, a specific problem, a change name or backlog slug, a comparison, or nothing.

**Context check** — at the start run `openspec list --json`. If a change or backlog slug is mentioned, read its artifacts (`openspec/changes/<name>/{proposal,design,tasks}.md`, or `openspec/backlog/{ideas,ready}/<slug>.md`).

Ground discussion in the actual codebase; ASCII diagrams are welcome. No fixed steps or required outputs.

**When decisions crystallize, offer (don't auto-capture) to record them:**

| Insight | Where |
|---|---|
| New / changed requirement | `specs/<capability>/spec.md` |
| Design decision | `design.md` |
| Scope change | `proposal.md` |
| New work | `tasks.md` |
| Groomed backlog idea (no open questions left) | move `ideas/<slug>.md` → `ready/<slug>.md` |

The user decides. Offer once and move on.
