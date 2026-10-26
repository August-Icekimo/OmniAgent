---
slug: multi-attachment-turn
status: idea
domain: brain
size: S
priority: P2
created: 2026-10-26
---

# 合併 turn 只分析最後一個附件，前面的圖片被佔位字取代

## Why
conversational-turn-assembly 把連發訊息合併成一個 turn，但 brain/main.py:812-816 刻意
「以 turn 內最後一個附件為準」（v1 best-effort）。2026-10-26 實測：照片 → 語音 → 貼圖連發，
合併 turn `b03d3c87` 只分析了貼圖，照片只剩佔位文字，Cindy 回覆「這張圖片我目前只收到圖片代碼，
看不到內容」—— 對使用者來說像是 Cindy 壞了，而且洩漏內部佔位字。家人傳圖常是連拍或圖＋貼圖。

## What (high-level)
合併 turn 中的每個圖片／貼圖附件都被分析（或至少不再以佔位字誤導模型），
回覆能涵蓋所有附件；無法分析的附件以自然語言誠實說明，不出現「圖片代碼」之類內部字樣。

## Acceptance hints
- 照片＋貼圖連發：回覆同時提到兩者內容
- 兩張照片連發：兩張都被描述
- 語音仍走 faster-whisper 轉文字，不受影響
- 單一附件 turn 行為與延遲不變

## Open questions
- 多附件逐一跑 file_analyzer（延遲累加），還是把多張圖一次送給視覺模型（ChatGPT／Gemini 皆支援多圖）？
- 附件數上限與超量時的處理？

## Links
- Related: brain/main.py turn 組裝（_process_turn_core）、brain/agent/graph.py plan_node（單一 attachment）、
  brain/skills/file_analyzer.py
- Related idea: conversational-turn-assembly（resolved，合併機制來源）
- 發現於：docs/change_local-llm-retirement.md Task 5c 驗收
