---
slug: line-video-ingestion-gap
status: idea
domain: gateway
size: M
priority: P2
created: 2026-06-20
---

# LINE 影片訊息沒接線（gateway 靜默丟棄）

## Why
2026-06-20 調查：從 LINE 傳影片，brain 根本收不到內容，卡在 gateway。
[gateway/internal/handler/line.go](../../../gateway/internal/handler/line.go) 的
message switch 只處理 `image` / `audio` / `sticker`，**沒有 `video` case，也沒有
default**。影片訊息因此：
- 不會 `downloadLineContent`，`attachment` 為 `nil`
- `messageType` 維持 `"video"`、`text` 為空
- 照樣塞進 `message_queue`，但帶空內容 → brain 端無料可分析

能力其實齊全，只缺 LINE 這段下載接線：
- 路由：`brain/llm/router.py` `msg_type in ["voice","video"]` 已強制走 Gemini
- 分析：`brain/skills/file_analyzer.py` `_analyze_video` 已用 Gemini Native Video
- 對照組：Telegram 有完整 `Video` 分支（telegram.go），TG 傳影片正常判讀

註：LINE 沒接線是 Phase 4D 當初的設計決定（archive spec 把 short video /
video > 10s 列 out-of-scope，僅 log warning + 文字 placeholder），非退化 bug。

## What (high-level)
在 LINE handler 補 `case "video"`，走現成的 Message API content endpoint
（與 image/audio 同路，`downloadLineContent` 可重用），設定
`MediaType="video"` 並帶 `DurationMs`，與 Telegram 分支對齊。

## Acceptance hints
- LINE 傳影片時 gateway 下載成功並產生 attachment，brain 走 Gemini 影片分析回出描述
- 與 Telegram 影片行為一致（MediaType / DurationMs）

## Open questions
- **檔案大小**：file_analyzer 目前把整支影片 base64 inline 塞進請求，未走
  Gemini File API。一分多鐘影片可能撞 inline ~20MB 上限 → 需要大小判斷
  或改走 File API upload（此題 Telegram 影片同樣有，建議一併處理）。
- LINE content endpoint 對大型影片是否有自己的下載上限／需分段？

## Links
- Related: gateway/internal/handler/line.go（缺 video case）
- Related: gateway/internal/handler/telegram.go:205-215（對照實作）
- Related: brain/skills/file_analyzer.py:309（_analyze_video，inline base64 隱憂）
- Context: openspec/changes/archive/2026-04-29-phase4d-multimodal（當初 out-of-scope 決定）
