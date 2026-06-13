---
slug: conversational-turn-and-threading
status: idea
domain: brain
size: L
priority: P1
created: 2026-06-13
---

# Human Conversation: Turn-Taking and Topic Threading

## Why
TG/LINE present as a single linear window, but humans interleave several topics
in it and split one thought across multiple messages. Cindy has no framework to
separate interleaved topics and currently replies message-by-message — so she acts
on half-finished thoughts (and on information a later message supersedes), and loses
track of which open loops she still owes. Affects every family member on Telegram/LINE.

## What (high-level)
Cindy recognises the shape of human conversation: she waits for a thought to finish
before responding instead of replying per message, tells apart distinct topics
interleaved in one window, keeps track of which open loops are still owed and by whom,
and consolidates or resurfaces them the way an attentive person would — including
handling a human's "still there?" nudge as a continuation of what she already owes
rather than a new topic.

## Acceptance hints
- A rapid burst on one topic produces a single consolidated reply, not one per message.
- A correction sent mid-burst supersedes the earlier message before Cindy acts on it.
- Two topics interleaved in one window are tracked separately and answered to the right one.
- A bare "still there?"-style nudge re-activates the loop Cindy already owes, not a new topic.
- A new message arriving while Cindy is mid-answer does not spawn a parallel reply
  (turn-atomicity holds up to a defined commit point).

## Open questions

**Turn assembly (debounce)**
- Timer reset-on-each-message vs fixed-from-first (patience vs simplicity; the latter
  cuts off slow typists).
- CJK weakness: casual mixed CN/EN chat often omits terminal punctuation, so the
  linguistic "turn complete" signal is weak and weight falls back onto timeout.
- Completeness check lives where: cheap gateway regex/rules vs a local-model call
  (keep gateway purely mechanical vs let the brain judge).
- Concrete timings: silence window (~3–5s candidate), max-wait ceiling; verify the
  exact LINE reply-token expiry window.

**LINE delivery economics**
- Confirm the re-trigger ladder when a turn outlives the reply-token window:
  re-trigger element (postback / quick-reply / LIFF that round-trips) → ride-along on
  the user's next organic inbound → push only for urgency-flagged turns. Define the
  urgency flag (shared with the debounce-floor skip).
- Cindy-initiated stale-resurfacing has no inbound to ride on, so it must push (quota
  cost) or wait for organic contact — how aggressive should resurfacing be given that?

**Threading & "whose turn" state**
- Phase 1 implicit (tag each turn to a topic) vs phase 2 explicit (open loops with an
  owner-of-next-turn): do both ship under this card, or does threading split out later?
- Ambiguous attribution fallback (a wrong guess is worse than no threading): default to
  the most-recent owed loop, ask, or something else?
- When does a topic become closed: explicit signal, inferred completion, or stale-decay?
- Concurrent-loop cap per person: unbounded vs a human working-memory bound (a handful)
  plus an eviction policy — ties to the "memory as native cognition" axis.
- Nudge = reverse resurface of an owed loop; attribution must support an
  owner-of-next-turn reverse lookup. A bare nudge with several owed loops → consolidate
  and answer all of them?
- Intra-burst multi-topic (one burst, two topics): v1 assumes one-burst-one-topic; defer.

**Brain interruptibility**
- Where is the commit point in the graph: before it the turn can absorb appends / be
  superseded; after it new input starts the next turn rather than mutating the current one.
- Scope interruptibility to the upgraded/expensive ModelRouter path only (cancel on user
  withdrawal to save the 20/day upgrade quota); cheap/local turns run atomic and reconcile
  at flush. Confirm this scoping.

**Scope & domain**
- Scope: Telegram + LINE only; BlueBubbles excluded (frozen, 4E-deprecated); 1:1 only,
  group chats deferred ("whose ball is it" explodes with multiple humans).
- Multi-domain smell: this touches brain + gateway + memory — during grooming, decide
  whether to split or keep unified.

## Links
- Roadmap: openspec/backlog/ROADMAP.md (no confirmed anchor — candidate: Phase 5 Family
  Preference Awareness or Phase 6 Memory; confirm placement during grooming)
- Related spec: openspec/specs/brain/spec.md (primary); also gateway, memory
- Depends on: none
