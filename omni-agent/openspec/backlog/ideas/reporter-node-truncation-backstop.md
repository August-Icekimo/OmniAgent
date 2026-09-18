---
slug: reporter-node-truncation-backstop
status: resolved
domain: brain
size: S
priority: P2
created: 2026-06-10
resolved: 2026-09-19
resolution: won't-do
resolved_by: openspec/backlog/sprints/2026-W38.md
---

> **關卡（2026-09-19，won't-do）。** 本卡四度（W24/W26/W36/W38）未動工，W36 retro 預立
> 「W38 再未動即關」。開工前查證，發現卡片的兩個前提都已不存在：
>
> 1. **要對齊的 planner 保底已被移除。** dd1b691 的 `finish_reason == "length"` 升級重試
>    在 PR #10（commit `772f663`「tool-call 迴圈取代 prompt-JSON planner + 移除升級舉旗」）
>    整條拆掉，現在 `brain/agent/` 內沒有任何 `finish_reason` 處理，無「一致」可言。
> 2. **「skill 結果報告」路徑已不經 reporter_node。** 同一次重構後 skill 結果由 agent
>    工具迴圈回饋模型續跑；`reporter_node` 現僅服務 file_analyze 感知回覆（貼圖／語音描述），
>    輸出短，本卡 open question 自己已指出這條路徑「只需 log 不需重試」。
>
> 若長輸出截斷仍是活問題，屬全新前提（agent 迴圈層是否需要截斷偵測），另開新卡，
> 不沿用本卡。下方原始內容僅作歷史記錄。

# reporter_node 缺截斷保底（finish_reason）

## Why
2026-06-10 在 planner_node 加入了 `finish_reason == "length"` 確定性升級保底
（dd1b691），但 reporter_node 的兩條 LLM 呼叫路徑（file_analyze 感知回覆、
skill 結果報告）沒有同等保護 — selected_provider 為 local 時長輸出仍會斷尾出貨。

## What (high-level)
reporter_node 的 router.chat 回應檢查 finish_reason，被硬截時升級重試
（或至少 log warning），與 planner 行為一致。

## Acceptance hints
- local 在 reporter 路徑被 max_tokens 硬截時不會把斷尾文字出貨
- 升級重試沿用「舉旗/空回應不出貨」防線

## Open questions
- 感知路徑（貼圖/語音描述）輸出通常短，是否只需 log 不需重試？

## Links
- Related: brain/agent/graph.py reporter_node
- Depends on: 已完成的 planner 保底（commit dd1b691）
