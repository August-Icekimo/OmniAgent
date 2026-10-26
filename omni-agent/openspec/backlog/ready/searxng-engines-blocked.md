---
slug: searxng-engines-blocked
status: in-sprint
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

## Grooming 結論（2026-10-26，實測）
- **逐引擎實測**（現行 image 2026.6.8，查詢「台北 天氣」）：bing 10 筆、yandex 15 筆、bing news 10 筆可用；
  brave `too many requests`（暫時 suspend 180s）、duckduckgo／startpage／google news CAPTCHA、qwant access denied、
  google 0 筆、yahoo／presearch HTTP error。
- **品質**：bing 中文結果優（首筆即中央氣象署官方頁）；yandex 中文結果差（垃圾站、港媒、舊聞）→ 不採用。
- **bing 在 SearXNG 預設 `disabled: true`** → 這是 general 分類只剩三個易被封引擎的主因。
- **升級有效**：最新 image `2026.10.25-54ca1d9cf` 暫時容器實測 general 27 筆、brave 19 筆恢復（google／qwant 仍拒）。
- **出口 IP**：CAPTCHA／access denied 集中在 google 系、ddg、startpage、qwant，研判 HomeLab 出口 IP 信譽問題，
  無法根治 → 以引擎多樣化（加 bing）＋錯誤可辨識緩解；暫不需付費搜尋 API。
- 方案：image 釘版 2026.10.25、settings.yml 啟用 bing、web_search 在引擎全滅時回報可辨識錯誤。

## Links
- Related: brain/skills/web_search.py、compose.yml（searxng 服務）、searxng/ 設定目錄
- 發現於：docs/change_local-llm-retirement.md Task 2 驗證
