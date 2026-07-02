---
slug: local-prompt-cap-preflight
status: idea
domain: llm
size: S
priority: P2
created: 2026-07-02
---

# Local 路由前置檢查 prompt 長度，>8k 直接 fallback 不打 local

## Why
rapid-mlx（--mllm 模式）的 `--prefill-step-size 8192` 是 hard per-batch prompt cap，
且是**這台 32GB 機的硬體上限**（2026-07-02 實測定案：16384 會讓 9.5k prompt 單
chunk prefill Metal OOM 整台崩；chunked-prefill 在 --mllm 不生效；邊界 6.4k OK /
9.5k 崩）。生產已出現 8.5k–9.4k 的 turn prompt（組裝＋歷史＋tool specs 成長）被
拒收 — local 端回 HTTP 400（0.9.10 起 pre-admission，乾淨但仍浪費一次往返），
brain 才靠錯誤 fallback。cap 不可調大，長 prompt 本地無解，這類請求的正確去處
本來就是 gemini（或 AGY specialist 長文摘要委派）。

## What (high-level)
brain `local_client`（或 router 選 local 前）粗估 prompt token 數（中文 ≈ 每字
0.7–1 token，寧可高估），超過安全閾值（如 7500，留 headroom）就跳過 local、
直接走 fallback chain 下一家 — 省掉一次必然失敗的 HTTP 往返與錯誤解析。

## Acceptance hints
- >8k prompt 的 turn 首發即走 gemini/claude，local 端 err.log 不再出現
  `exceeds the per-batch cap` 拒收記錄
- 一般短 turn 路由行為不變（local 維持短快定位）
- 閾值可設定（env 或 routing_config.json），不硬編；rapid-mlx 換機/換 cap 時只改設定
- 與 routing-long-output-detection 互補：那張管長「輸出」意圖，這張管長「輸入」實測長度

## Open questions
- token 估算用字元數啟發式就夠，還是掛 tokenizer？（傾向啟發式：寧可高估提早 fallback，
  錯殺代價只是多用一次雲端）
- 長文摘要類是否直接建議 planner 選 `delegate_to_specialist`（AGY）而非 gemini 代打？

## Links
- Related: brain/llm/router.py select_provider、brain/llm/local_client.py、
  brain/config/routing_config.json
- Related idea: routing-long-output-detection（長輸出意圖，互補）
- Related: antigravity-a2a-integration-path（AGY 長文摘要委派，PR #13）
- 實測依據：rapid-mlx 0.9.10 @ chrysoberyl，2026-07-02（16384 OOM 崩、8192 定案）
