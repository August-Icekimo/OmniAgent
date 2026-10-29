---
slug: llm-usage-accounting
status: resolved
domain: llm
size: XS
priority: P2
created: 2026-10-29
resolved: 2026-10-29
resolved_by: db/migrations/011_llm_usage.sql + brain/llm/router.py `_record_usage`（W44 Stretch，XS 不另開 change doc）
---

> **已解決（2026-10-29）。** Open questions 由 admin 定案：開新表 `llm_usage`、實測各家 reasoning 欄位、一併記延遲。
> 實作：每次 `Router.chat` 的 provider 嘗試（含失敗、含 fallback）fire-and-forget 寫一筆；
> 不放 user_id／turn_id（router 拿不到，觀察期以時間對 turns 即可）。
>
> **實測各家 reasoning 欄位**：ChatGPT `output_tokens_details.reasoning_tokens`、Claude `output_tokens_details.thinking_tokens`
> 皆**已含**在 output_tokens；Gemini `thoughts_token_count` **不含**在 `candidates_token_count` →
> 原本 Gemini usage 少算思考 token（實測「17*23」思考 211、可見輸出 3），已改為 output = candidates + thoughts。
> 容器內 smoke：三 provider 成功各一筆、chatgpt 模擬失敗 → 失敗一筆（`RuntimeError`）＋ gemini `fallback=true` 一筆；測試資料已清除。
> 觀察查詢已加入 docs/change_local-llm-retirement.md Testing Notes。

# 記錄每次 LLM 呼叫的 token 用量（provider／model／caller）

## Why
ChatGPT Plus 改為 Cindy 主力後，local-llm-retirement Task 6 要判斷「額度消耗是否影響 admin 個人使用」，
但 SIWC 拿不到剩餘額度：2026-10-29 實測 `/v1/responses` 標頭與串流事件皆無 rate-limit 資訊
（Codex CLI `/status` 的百分比來自 Codex 自家後端，非 SIWC 路徑），`/v1/usage`／`/v1/me` 401、`/v1/rate_limits` 404，
官方文件亦無查詢方式。目前唯一的量化來源是 ChatGPT Settings → Usage 手動讀數。
另一方面每次呼叫的 token 數其實已拿到（`response.completed.usage` → `LLMResponse.usage`），
只用於回覆 footer 的 context 百分比，用完即丟。

## What (high-level)
在 router 層（所有呼叫的共同出口）記錄每次**成功**呼叫的 provider、model、caller、input／output／reasoning／cached tokens，
讓觀察期能回答「Cindy 每週在各 provider 用了多少」，作為手動額度讀數的相對量佐證。
一個使用者回覆可能含多次呼叫（tool 迴圈、OCR、足夠性判斷、長期記憶摘要），只記最後一次會低估，故不在 conversation 層記。

## Acceptance hints
- 所有 `Router.chat` 成功呼叫都留紀錄，含 caller（現有 13 處已帶 `caller=`，未帶的記 `unknown`）
- fallback 命中時記實際成功的 provider；失敗的嘗試不計 token
- local-llm-retirement Testing Notes 的觀察查詢新增「每週 provider × token 加總」
- 寫入失敗不影響回覆（best-effort，同 short_term.save 的 fire-and-forget 模式）

## Open questions
- 存放處：新表 `llm_usage`（需 schema 變更、先經 admin 確認）vs 結構化 log 行（零 schema，但容器重建即歸零，
  與 Task 4 已知的 log 限制相同）。傾向新表。
- reasoning tokens：ChatGPT 有 `output_tokens_details.reasoning_tokens`；Gemini thinking／Claude 的對應欄位需確認各 client 是否已收進 `usage`
- 是否同時記延遲（每次呼叫 ms），順便回答「延遲花在哪一段」（Task 5 未達的延遲 AC）

## Links
- Related change: docs/change_local-llm-retirement.md（Task 4 觀察紀錄、Task 6 額度決策）
- Related code: brain/llm/router.py `chat`、brain/llm/chatgpt_client.py usage 收集
- 發現於：2026-10-29 SIWC usage 探查
