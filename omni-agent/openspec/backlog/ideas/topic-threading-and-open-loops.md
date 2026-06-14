---
slug: topic-threading-and-open-loops
status: idea
domain: brain
size: L
priority: P1
created: 2026-06-13
groomed: 2026-06-14
---

# Topic Threading & Open-Loop Accounting

## Why
Humans interleave several topics in one TG/LINE window. Even once Cindy assembles
a turn ([conversational-turn-assembly]), she can't tell apart distinct topics
interleaved in the same window, and loses track of which open loops she still owes
and to whom — so she answers the wrong thread and drops things she promised.
Affects every family member on Telegram/LINE (1:1).

## What (high-level)
Cindy tells apart distinct topics interleaved in one window, keeps track of which
open loops are still owed and by whom (owner-of-next-turn), consolidates or
resurfaces them the way an attentive person would, and handles a bare "still
there?" nudge as a continuation of an owed loop rather than a new topic.

Builds on [conversational-turn-assembly] (turn boundaries + atomicity must exist
first).

## Decisions (groomed 2026-06-14)
- **Phasing within this card**: ship both phase 1 (implicit — tag each turn to a
  topic) and phase 2 (explicit — open loops with an owner-of-next-turn). Phase 2's
  reverse owner-of-next-turn lookup is what makes nudge handling work.
- **Resurfacing aggressiveness**: **conservative**. A stale owed loop rides along
  on the user's next organic inbound; Cindy pushes (LINE quota cost) only for
  loops flagged urgent. No proactive push of non-urgent loops.
- **Concurrent-loop cap per person**: human working-memory bound (~5–7 candidate)
  with an eviction policy (evict oldest/stalest when full). Ties to the "memory as
  native cognition" long-term axis rather than unbounded state.
- **Ambiguous attribution fallback**: a wrong guess is worse than no threading —
  default to the most-recent owed loop; if several loops are plausibly owed, ask
  rather than guess.
- **Nudge handling**: a bare nudge = reverse-resurface of an owed loop via the
  owner-of-next-turn lookup. If several loops are owed, consolidate and answer all.
- **Scope**: Telegram + LINE, 1:1 only. Intra-burst multi-topic (one burst, two
  topics) deferred — v1 assumes one-burst-one-topic. Group chats deferred.

## Acceptance hints
- Two topics interleaved in one window are tracked separately and answered to the right one.
- A bare "still there?"-style nudge re-activates the loop Cindy already owes, not a new topic.
- A loop Cindy owes survives across turns and is resurfaced (ride-along) when the user returns.
- Ambiguous attribution falls back to the most-recent owed loop, or asks when several are owed.

## Open questions (residual — implementation discovery, not grooming)
- Topic-close trigger: explicit signal, inferred completion, or stale-decay — or a
  combination. Confirm the decay window for stale-decay.
- Where open-loop / whose-turn state lives: new table vs existing memory tables;
  reverse owner-of-next-turn lookup shape. (Schema-first — confirm DB changes.)
- Tuning the loop cap (~5–7) and eviction signal (age vs staleness) against real use.
- Urgency-flag definition is shared with [conversational-turn-assembly]; align both.

## Links
- Roadmap: openspec/backlog/ROADMAP.md (Phase 6 Memory — "memory as native cognition")
- Related spec: openspec/specs/brain/spec.md (primary); also memory, gateway
- Depends on: conversational-turn-assembly
