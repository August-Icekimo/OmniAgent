---
slug: searxng-engines-blocked
status: idea
domain: skills
size: S
priority: P1
created: 2026-10-26
---

# SearXNG 搜尋引擎全數被封，web_search 永遠零結果

## Why
2026-10-26 實測：brain → `http://searxng:8080/search` 回 200 但 `results: 0`，
`unresponsive_engines` 全滅 —— brave `Suspended: too many requests`、duckduckgo `CAPTCHA`、
startpage `Suspended: CAPTCHA`。Cindy 的 `web_search` 工具因此對任何問題都回「沒有搜尋結果」，
模型只能道歉。使用者問天氣、新聞等需上網的問題全部失敗，且沒有任何告警。

## What (high-level)
讓 web_search 恢復穩定產出結果：調整 SearXNG 引擎組合／限流設定，或引入不易被封的搜尋來源
（例如官方 API 型引擎），並在引擎全滅時讓工具回報明確錯誤而非空結果。

## Acceptance hints
- 一般查詢（天氣、新聞、人名）web_search 回傳 ≥1 筆結果
- 引擎全數 unresponsive 時，工具回傳可辨識的錯誤（讓模型告知使用者「搜尋服務暫時無法使用」而非「查無資料」）
- 有辦法察覺此狀態（log WARNING 或納入 preflight 類啟動檢查）

## Open questions
- 換引擎組合（google／bing／wikipedia 等）是否足以避開 CAPTCHA？還是需要付費搜尋 API？
- searxng 容器是 `searxng/searxng:latest` 跑 5 週未更新 —— 升級是否就能改善部分引擎？
- 對外 IP 是否已被標記（HomeLab 單一出口 IP），影響所有爬取型引擎？

## Links
- Related: brain/skills/web_search.py、compose.yml（searxng 服務）、searxng/ 設定目錄
- 發現於：docs/change_local-llm-retirement.md Task 2 驗證
