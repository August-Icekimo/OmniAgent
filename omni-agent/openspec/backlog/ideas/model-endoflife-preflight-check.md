---
slug: model-endoflife-preflight-check
status: idea
domain: llm
size: S
priority: P1
created: 2026-08-29
---

# Model 退役偵測：provider chain 靜默降級無人知道

## Why
**Claude provider 從 2025-10 到 2026-07 實質 404 了八個月，沒人發現。**
`routing_config.json` 釘的 `claude-3-5-sonnet-20241022` 於 2025-10-28 退役、
`claude_client.py` 預設的 `claude-sonnet-4-20250514` 於 2026-06-15 退役
（commit 7c39045 查證）。因為 router 有 fallback chain，退役不是「壞掉」而是
**靜默降級** —— 表面一切正常，實際少一家 provider。

代價已經具體發生過：W26 review 的 I5「planner 自動選用 delegate_to_specialist」
一度無法驗證、被誤判為 tool-calling 設計問題，實際只是 Claude 打不通。
換掉 model id 後同一測試 Claude 2/2 通過。**壞的 provider 汙染了對其他功能的判斷。**

同類事件密度不低：Gemini 403 quota（2026-06→07）、claude-sonnet-5 上市但非
drop-in（帶 temperature 會 400）。這是「會週期性再發生」的一類問題，而 W26 retro
只把它寫成一條散文教訓 —— 沒有機制，下次照樣八個月後才知道。

## What (high-level)
一個能定期跑的 preflight：對 `routing_config.json` 內**每一個** model id
（含 `upgrade_model`）發一次極小的真實請求，回報 ok / 4xx / 退役。

- 覆蓋設定檔 **與** client 端預設值兩處 —— 這次就是兩處都過期，且 client 預設
  平時被 config 覆寫、只在 fallback 路徑現形，最難察覺
- 輸出人可讀結果（哪家通、哪家 404/403、實際回應 model id）
- 執行方式：先做成可手動跑的腳本（比照 `test_router.py`），能跑再談要不要接
  cron 或 admin 主動通知
- 順帶把 brain `/health`（[main.py:356](../../../brain/main.py#L356) 目前只回
  `{"status":"ok"}` 硬編）是否納入 provider 狀態一併評估

## Acceptance hints
- 一個指令能列出所有設定的 model id 及其實測可用性，含 local/gemini/claude
- 任一 model id 退役或無權限時，輸出明確指出是哪個 id、哪個檔案、什麼錯誤
- 每個 provider 僅耗極小 token（1 個 token 的 ping 級請求）
- `skip_in_test: true` 的 provider（local）可跳過或另行處理

## Open questions
- 只做手動腳本，還是接排程？（傾向先手動 —— 排程要處理通知去向與噪音，
  但手動的東西照經驗不會有人記得跑，這是本卡的核心張力）
- 通知走 admin proactive 訊息（比照 breaker 的 admin 通知）還是只寫 log？
- 要不要一併偵測「新版可用」（如 claude-sonnet-5）而非只偵測「舊版已死」？
  —— 注意 sonnet-5 非 drop-in（temperature 會 400），偵測到也不能自動換

## Links
- Roadmap: openspec/backlog/ROADMAP.md#2026-q3--phase-59-agent-capabilities
- 來源：openspec/backlog/sprints/archive/2026-W26.md 實測教訓 #3
- 證據：commit 7c39045（兩處退役 id）、docs/archive/review_pr13_*.md（I5 誤判）
- Related: brain/llm/router.py、brain/config/routing_config.json、
  brain/llm/claude_client.py、test_router.py
