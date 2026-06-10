---
slug: longterm-summarization-empty
status: idea
domain: memory
size: S
priority: P2
created: 2026-06-10
---

# 長期記憶摘要反覆回空（Summarization returned empty content）

## Why
2026-06-10 實測 log 中 `brain.memory.long_term` 反覆出現
「Summarization returned empty content, using fallback」。摘要持續失敗代表
長期記憶品質在退化（fallback 可能存原文或低質內容），且歷史上的記憶汙染
事故（舉旗 JSON 入庫）顯示這條路徑的內容品質值得嚴格把關。

## Why（補充風險）
fallback 寫入的內容若包含模型控制訊號或殘缺文字，會在日後 recall 時
注入 system prompt 誘導模型（2026-06-10 已實際發生過一次學舌事故）。

## What (high-level)
- 查明摘要回空的原因（provider 選擇？prompt？thinking 模式吃掉輸出？
  與 gemma enable_thinking/mlx-lm issue #1352 的空回應是否同源？）
- fallback 行為審視：存什麼、要不要過濾控制訊號與斷尾內容
- 摘要失敗加上可觀測性（計數/告警）

## Acceptance hints
- 正常對話結束後摘要成功率明顯改善，log 不再頻繁出現該警告
- fallback 寫入內容有基本品質過濾（無控制 JSON、無句中斷尾）

## Open questions
- 摘要用哪個 provider 最划算（local 免費但回空可能正是 local 造成）？

## Links
- Related: brain/memory/long_term.py
- Origin: docs/archive/change_ideas-from-hermes.md 實測期間發現
