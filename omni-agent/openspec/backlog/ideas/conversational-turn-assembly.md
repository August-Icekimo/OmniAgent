---
slug: conversational-turn-assembly
status: idea
domain: brain
size: L
priority: P1
created: 2026-06-13
groomed: 2026-06-14
---

# Conversational Turn Assembly & Atomicity

## Why
TG/LINE present as a single linear window and humans split one thought across
several messages. Cindy replies message-by-message, so she acts on half-finished
thoughts and on information a later message supersedes. Affects every family
member on Telegram/LINE (1:1).

## What (high-level)
Cindy waits for a thought to finish before responding instead of replying per
message: the gateway assembles a burst of messages into one **turn**, and the
brain treats that turn atomically up to a defined commit point so a late append
folds into the current turn rather than spawning a parallel reply.

This is the foundation for [topic-threading-and-open-loops]; threading is **out
of scope** here — v1 assumes one-burst-one-topic.

## Decisions (groomed 2026-06-14)
- **Debounce model**: reset-on-each-message silence timer (~4s candidate) with a
  hard max-wait ceiling (~30s candidate) so a slow typist can't starve the turn.
  Tolerant of CJK casual chat that omits terminal punctuation, where the
  linguistic "turn complete" signal is weak and weight falls back on the timeout.
- **Completeness check location**: the gateway stays **purely mechanical** —
  timer + cheap signals only (message arrival, optional typing indicator). Any
  semantic "is this thought actually finished" judgement lives in the brain, not
  the gateway. (Consistent with the gateway's existing role.)
- **Interruptibility — ALL paths cancel-on-withdrawal** (revised 2026-06-14 after
  verifying Rapid-MLX; supersedes the earlier "upgraded-path-only" framing from the
  original combined idea):
  - Upgraded path (Claude/Gemini): asyncio cancel of the in-flight SDK call —
    aborts the HTTP request and stops further billing / the 20/day quota burn.
  - Local path: **Rapid-MLX *does* support aborting a running request** —
    `scheduler._do_abort_request` removes it from the live BatchGenerator and frees
    Metal cache, processed at the top of every `step()` (`vllm_mlx/scheduler.py`);
    `engine_core.py:909` also aborts on client disconnect. To use it the brain must
    switch local calls to **streaming** (to capture the `chatcmpl-` id), track that
    id, and `POST /v1/requests/{id}/cancel` on withdrawal. **Caveat:** the endpoint
    returns `cancelled:true` unconditionally — it is NOT proof of an abort; confirm
    by observed effect (see Acceptance hints / residual questions).
  - Debounce stays the *primary* mechanism: it catches most supersession before the
    commit point; cancel only handles a late append that lands after commit.
- **Local prompt cache**: enable the Rapid-MLX server prompt cache (currently
  `cache.enabled=false`; advertised cached TTFT ~0.08s) and have the brain local
  client opt in (today `cached=False`, [local_client.py:207](../../../brain/llm/local_client.py#L207)).
  This is the high-CP local lever — makes a debounced/settled-burst re-run cheap and
  far outweighs interruption savings on the local (no-quota, no-cost) path.
- **Prerequisite**: per-user serialization. There is no per-user lock today —
  messages from one user can process concurrently — which both turn-atomicity and
  cancellation require.
- **Scope**: Telegram + LINE, 1:1 only. BlueBubbles excluded (frozen,
  4E-deprecated). Group chats deferred.

## Acceptance hints
- A rapid burst on one topic produces a single consolidated reply, not one per message.
- A correction sent mid-burst supersedes the earlier message before Cindy acts on it.
- A new message arriving while Cindy is mid-answer does not spawn a parallel reply —
  turn-atomicity holds up to the commit point (append absorbed before it; new turn after it).
- A correction arriving *after* generation has started cancels the in-flight turn
  (local AND upgraded) before the superseded reply is sent.
- Cancellation is confirmed by *observed effect* (generation actually stops), not by
  the cancel endpoint's `200 cancelled:true` (which is unconditional).
- A turn that outlives the LINE reply-token window still gets delivered via the
  re-trigger ladder (below), not dropped.

## Open questions (residual — verification, not grooming)
- **Local abort wiring**: verify the correct `request_id` to pass to
  `/v1/requests/{id}/cancel` and that it maps to the scheduler's `request_id_to_uid`;
  confirm the abort actually halts generation and frees the GPU. A live by-the-docs
  test (cancel via the SSE `chatcmpl-` id) returned `200 cancelled:true` but
  generation continued ~44s — the 200 is a false positive, so this needs hands-on
  confirmation. (Reusable curl recipe in the grooming plan.)
- **Local prompt cache**: enable + validate it on the Rapid-MLX server
  (`cache.enabled=false` today) and confirm the brain's opt-in actually reuses KV.
- Concrete debounce tuning: confirm silence window (~4s) and ceiling (~30s) against
  real family chat behaviour after a first cut.
- **LINE reply-token expiry**: verify the exact reply-token window, then confirm
  the reactive re-trigger ladder when a turn outlives it — re-trigger element
  (postback / quick-reply / LIFF that round-trips) → ride along on the user's next
  organic inbound → push only for urgency-flagged turns. Define the urgency flag
  (shared with the debounce-floor skip). (Proactive Cindy-initiated resurfacing is
  out of scope here — see [topic-threading-and-open-loops].)
- Exact graph commit-point location in `brain/agent/graph.py`: where appends can
  still be absorbed vs where a new input starts the next turn.
- Per-user serialization shape (now a hard prerequisite): per-user dequeue /
  in-flight lock — no per-user lock exists today.

## Links
- Roadmap: openspec/backlog/ROADMAP.md (near-term brain conversation-quality;
  slots around/before Phase 5 — confirm placement at sprint planning)
- Related spec: openspec/specs/brain/spec.md (primary); also gateway
- Depends on: none
- Blocks: topic-threading-and-open-loops
