---
slug: provider-override-merged-turn
status: idea
domain: brain
size: XS
priority: P2
created: 2026-10-26
---

# `/provider` 覆蓋在多訊息合併的 turn 中失效

## Why
`plan_node` 只在「最後一則訊息文字以 `/provider ` 開頭」時套用手動 provider 覆蓋
（brain/agent/graph.py:226-231）。conversational-turn-assembly 會把同一輪多則訊息合併；
2026-10-26 實測：前一則「還在嗎？」被撤回後重新排入，與 `/provider gemini 今天台北天氣如何？`
合併成一個 turn（`10b7847a`，2 msgs），覆蓋被忽略、照樣路由 local。admin 在 Cindy 卡住時
最需要用覆蓋指令救急，偏偏此時最容易有殘留訊息被合併。

## What (high-level)
在合併後的 turn 中，只要任一則（或最後一則原始訊息）是 `/provider <name> ...`，覆蓋即生效，
且指令前綴從送給模型的內容中移除。

## Acceptance hints
- 單則 `/provider gemini xxx` 行為不變
- 殘留訊息 + `/provider gemini xxx` 合併成同一 turn 時，executor 為 gemini
- 指令文字不出現在模型輸入與存回歷史中

## Open questions
- 合併 turn 中出現多個不同 `/provider` 時取哪一個（傾向最後一個）？
- 判斷依據用合併前的原始訊息清單（需確認 main.py 組裝時是否保留邊界），還是在合併文字中逐行掃描？

## Links
- Related: brain/agent/graph.py plan_node、brain/main.py turn 組裝
- Related idea: conversational-turn-assembly（resolved，合併機制來源）
- 發現於：docs/change_local-llm-retirement.md Task 2 驗證
