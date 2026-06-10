---
slug: routing-long-output-detection
status: idea
domain: llm
size: S
priority: P2
created: 2026-06-10
---

# 路由規則偵測長輸出意圖，避免浪費一輪 local

## Why
`short_simple` 規則只看「輸入長度 < 50」，「寫 5000 字的故事」這類短輸入長輸出
請求會先送 local（max_tokens 1024）跑滿 1-2 分鐘被硬截，才靠 finish_reason
保底升級 gemini 重來 — 功能正確但每次浪費約 2 分鐘等待與一輪本地推理。

## What (high-level)
routing_rules 增加長輸出意圖條件（如 text 含「N 字」「寫一篇/寫文章/故事/報告」
等 pattern），命中直接路由 gemini，跳過 local 那一輪。

## Acceptance hints
- 「寫 4000 字…」類請求首輪即走 gemini，總延遲明顯下降
- 一般短訊息路由行為不變（local 維持短快定位）
- pattern 維護在 routing_config.json，不硬編在程式碼

## Open questions
- 中文「續寫/繼續」且前文是長文模式時要不要也直送 gemini？
  （目前靠 finish_reason 保底，可接受）

## Links
- Related: brain/llm/router.py select_provider、brain/config/routing_config.json
- Depends on: finish_reason 保底（已完成，作為 fallback 防線保留）
