---
slug: claude-vision-support
status: idea
domain: llm
size: S
priority: P2
created: 2026-10-26
---

# ClaudeClient 補上 image block 轉換，讓 Claude 成為視覺備援

## Why
`ClaudeClient.supports_vision()` 目前回 False（brain/llm/claude_client.py:147）：
模型本身支援 vision，但 client 沒把內部 image block 轉成 Anthropic source 格式，
原樣轉送會 400，所以 router 能力閘門一律跳過 Claude。local LLM 退役後
（local-llm-retirement），圖片／貼圖只剩 Gemini 一家能處理 — Gemini 一故障
（如 2026-10-26 的 prepay 402），Cindy 就完全失去視覺能力。

## What (high-level)
ClaudeClient 支援 Phase 4D 多模態 content list 中的 image part，轉為 Anthropic
image content block 後 `supports_vision()` 回 True，讓 router 在 Gemini 失敗時
能把圖片／貼圖 fallback 給 Claude。

## Acceptance hints
- 圖片／貼圖 turn 在 Gemini 不可用時由 Claude 回覆有意義的描述，而非誠實降級空回應
- audio/video 仍不送 Claude（router 能力閘門維持）
- 實機 smoke：照片 OCR、LINE 貼圖、TG 動態貼圖（轉 PNG 後）各一

## Open questions
- 內部 image part 格式（base64 / data URL / 檔案路徑）與 Anthropic source 型別的對應
- 圖片大小上限與壓縮策略（Anthropic 單張限制）是否需要前處理

## Links
- Related spec: openspec/specs/llm/spec.md
- Related: brain/llm/claude_client.py、brain/llm/router.py（多模態能力閘門）
- Related idea: local-llm-retirement（退役後視覺僅剩 Gemini，本卡補備援）
