Capture a new idea into the backlog.

I'll record your idea into `openspec/backlog/ideas/` for future grooming and planning.

---

**Input**: The argument after the command is the description or a kebab-case slug. Optional flags: `--domain`, `--why`, `--what`.

**Steps**

1. **If no description provided, ask what the idea is**
   Ask the user:
   > "What is your idea? Describe what you want to capture."

2. **Derive slug and check for collisions**
   - Derive a kebab-case slug from the description.
   - Check if `<slug>.md` exists in:
     - `openspec/backlog/ideas/`
     - `openspec/backlog/ready/`
     - `openspec/backlog/sprints/*.md` (Committed/Stretch tables)
   - If collision exists, abort with: "Slug `<slug>` already exists. Please use a different name or refine the idea."

3. **Elicit missing required fields**
   For each missing field (`why`, `what`, `domain`), ask the user:
   - `domain`: "Which domain does this belong to? (brain, gateway, identity, llm, memory, security, skills, soul)"
   - `why`: "Why is this needed? (the pain point or motivation)"
   - `what`: "What do you want to achieve? (high-level goal)"

4. **Validate domain**
   Ensure `domain` is one of: `brain`, `gateway`, `identity`, `llm`, `memory`, `security`, `skills`, `soul`.
   If mismatch, re-prompt the user.

5. **Write the idea file**
   - Use `openspec/backlog/_templates/item.md` as the template.
   - Populate frontmatter:
     - `slug`: `<slug>`
     - `status`: `idea`
     - `created`: `<today's YYYY-MM-DD>`
     - `domain`, `why`, `what` from inputs.
   - Write to `openspec/backlog/ideas/<slug>.md`.

6. **Show confirmation**
   Print the relative path and a 1-line summary.
