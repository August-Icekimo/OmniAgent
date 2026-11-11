Open a new 2-week sprint by selecting cards from `openspec/backlog/ready/`.

**Steps**

1. **Retro gate** — list `openspec/backlog/sprints/*.md` (excluding `archive/`). If one has `status: active` or an empty `Retro` section, abort: "Previous sprint `<path>` has no retro. Fill the Retro section then run again."
2. **ISO week** — `date +%G-W%V`. If `openspec/backlog/sprints/<YYYY>-W<NN>.md` exists, abort: "Sprint for this week already exists at `<path>`."
3. **Ready cards** — scan `openspec/backlog/ready/*.md`. Empty → abort: "No ready cards found. Run `/opsx-explore` on ideas or move ideas to ready first."
4. **Ask the user for:** theme & goals; committed cards (multi-select from ready cards); stretch cards (from the rest); capacity (e.g. "evenings + weekends ≈ 20h"); optional out-of-scope.
5. **Window** — start = Monday of the current ISO week; end = start + 13 days.
6. **Archive previous** — `git mv` any closed sprint file in `sprints/` into `sprints/archive/`.
7. **Write** `openspec/backlog/sprints/<YYYY>-W<NN>.md` from `openspec/backlog/_templates/sprint.md`: `sprint`, `window_start`, `window_end`, `status: active`, Theme, Goals, Committed, Stretch, Out of scope, Capacity.
8. Set `status: in-sprint` in each committed card's frontmatter.
9. Print the window, committed slugs, and stretch slugs.
