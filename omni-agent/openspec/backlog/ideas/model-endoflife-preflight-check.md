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
**主路徑：brain 啟動時的 preflight，不是手動腳本。**

`lifespan`（[main.py:263](../../../brain/main.py#L263)）建好 ModelRouter 後，對
`routing_config.json` 內每一個 model id（含 `upgrade_model`）各發一次 ping 級
請求，結果寫 log、失敗的出 WARNING。

選啟動檢查而非手動腳本的理由：**它掛在你本來就會做的動作上（`compose up`），
不掛在記性上。** 本卡要防的失效模式是「八個月沒人發現」—— 這期間 brain 必然
重啟過很多次，啟動檢查會在第一次重啟就叫出來；一個要人記得跑的腳本不會。

實作要點：

- **不得阻擋啟動**：比照 lifespan 現行的 STT／DB pool 寫法 —— try/except 包住、
  失敗只 log 不 raise。檢查本身建議在背景 task 跑，別讓幾個 API 往返拖長開機。
- **覆蓋設定檔與 client 端預設值兩處** —— 這次就是兩處都過期，且 client 預設平時
  被 config 覆寫、只在 fallback 路徑現形，最難察覺
- **log 要能直接動手**：哪個 id、在哪個檔案、什麼錯誤，不要只說「claude 失敗」
- local（`skip_in_test: true`）另行處理：rapid-mlx 可能整台沒開，屬預期狀況，
  語氣與雲端 provider 退役要能區分
- 手動腳本（比照 `test_router.py`）可順手包一層共用同一函式，但屬附帶產物，非主路徑

## Acceptance hints
- brain 啟動後 log 即可看出每個設定的 model id 是否可用，含 local/gemini/claude
- 任一 model id 退役或無權限時，log 明確指出是哪個 id、哪個檔案、什麼錯誤
- **provider 全掛時 brain 仍正常啟動並服務**（降級靠既有 fallback chain，不是靠這個檢查）
- 每個 provider 每次啟動僅耗極小 token（1 個 token 的 ping 級請求）
- 檢查可用 env 關閉（頻繁重啟除錯時不想每次打 API）

## Open questions
- 除了 log 之外要不要主動通知 admin？（比照 breaker 的 admin 通知路徑。傾向不要 ——
  開機噪音會讓通知貶值，log 先行，真的漏看再加）
- 要不要一併偵測「新版可用」（如 claude-sonnet-5）而非只偵測「舊版已死」？
  —— 注意 sonnet-5 非 drop-in（temperature 會 400），偵測到也不能自動換
- brain `/health`（[main.py:356](../../../brain/main.py#L356) 目前只回 `{"status":"ok"}`
  硬編）要不要吐出最近一次 preflight 結果？（分開評估，別讓本卡膨脹）

## Links
- Roadmap: openspec/backlog/ROADMAP.md#2026-q3--phase-59-agent-capabilities
- 來源：openspec/backlog/sprints/archive/2026-W26.md 實測教訓 #3
- 證據：commit 7c39045（兩處退役 id）、docs/archive/review_pr13_*.md（I5 誤判）
- Related: brain/llm/router.py、brain/config/routing_config.json、
  brain/llm/claude_client.py、test_router.py
