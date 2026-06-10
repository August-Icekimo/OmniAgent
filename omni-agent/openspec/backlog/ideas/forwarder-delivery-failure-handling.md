---
slug: forwarder-delivery-failure-handling
status: idea
domain: gateway
size: S
priority: P1
created: 2026-06-10
---

# forwarder 投遞失敗仍標記 done — 訊息靜默丟失

## Why
2026-06-10 實測踩到：Telegram 回 400（message too long）時 forwarder 只 log
錯誤，message_queue 照樣標 `done`，brain 已生成的答案永久丟失、使用者無感。
切段修正解決了該次起因，但「投遞失敗 = 靜默丟失」的結構問題仍在
（網路錯誤、平台 5xx、token 失效都會觸發）。

## What (high-level)
投遞失敗時不標 done：依錯誤類型標 `failed`（可重試）或進入重試（有限次數 +
退避），重試耗盡至少推送一則簡短錯誤通知給使用者。

## Acceptance hints
- 模擬平台 4xx/5xx：訊息不會靜默消失，log 與 queue status 可追蹤
- 重試不會造成重複投遞（LINE reply token 單次使用需排除在重試外）

## Open questions
- 重試走原 channel 還是降級（LINE reply 失敗改 push 已有，Telegram 呢）？
- 是否需要 dead-letter 狀態供人工檢視？

## Links
- Related: gateway/internal/forwarder/brain.go processNextMessage
- Origin: docs/archive/change_ideas-from-hermes.md 實測期間發現
