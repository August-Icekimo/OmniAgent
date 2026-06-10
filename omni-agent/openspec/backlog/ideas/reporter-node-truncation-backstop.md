---
slug: reporter-node-truncation-backstop
status: idea
domain: brain
size: S
priority: P2
created: 2026-06-10
---

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
