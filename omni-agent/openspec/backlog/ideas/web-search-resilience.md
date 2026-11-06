---
slug: web-search-resilience
status: idea
domain: skills
size: S
priority: P2
created: 2026-11-06
---

# 搜尋引擎被限流時不再整批落空

## Why
brain log（容器 10-30 起，55 次搜尋）：**8 次（≈15%）0 結果、引擎全滅**，全部集中在 10-30 密集使用時段（單日 30 次搜尋）。
- duckduckgo 幾乎常駐 CAPTCHA（44 次）
- brave／google cse 在密集查詢下被 SearXNG 判 too many requests 並 **suspend** 一段時間
- 剩下的 bing 對中文專有名詞、`site:` 查詢常無結果（11-06 實測「弈飛資訊」bing 0 筆）
Cindy 一個 turn 最多 5 輪工具迴圈，連續搜尋就把引擎一個個打掛。另外模型會寫出 `site.apps.apple.com`
（應為 `site:`）、過度加引號、`limit` 常只給 3，進一步壓低命中率。
10-26 `searxng-engines-blocked` 已解決「全部失效」，本卡處理的是「密集使用時的韌性」。

## What (high-level)
- **引擎池加厚**：評估再啟用不易被封的引擎（mojeek、qwant、startpage 等），讓限流時不會只剩 bing
- **限流參數**：檢視 SearXNG suspend 時間設定，避免一次 429 就把引擎停很久
- **工具描述補搜尋語法**：參考 hermes-agent 描述（`site:domain`、`filetype:pdf`、`-term`、`"exact phrase"`），
  並提示「0 結果時放寬關鍵字、減少引號再試一次」
- （選項）付費搜尋 API 當後備：hermes 的後端可抽換（Tavily／Exa／Parallel／Firecrawl 付費 > SearXNG／Brave free／DDGS 免費），
  且 search／extract 可分設不同家

## Acceptance hints
- 重現密集情境（短時間連續 ≥15 次搜尋）：引擎全滅比例明顯下降，且至少一個非 bing 引擎仍回結果
- 中文專有名詞查詢在 brave／google 被 suspend 時仍有結果
- 工具描述更新後，log 中不再出現 `site.` 誤寫
- 引擎全滅時的錯誤訊息維持現行區分（「引擎暫時無法使用」≠「查無資料」）

## Open questions
- 要不要引入付費搜尋 API？需新 key 與月費，且與 [[web-fetch-tool]] 的 extract 後端選擇一起決定較划算
- 新引擎的中文結果品質如何？需實測後再決定啟用清單
- 是否該在 brain 端加每 turn／每分鐘搜尋次數節流，而不是只靠 SearXNG？

## Links
- Related spec: openspec/specs/skills/spec.md
- 前作：docs/archive/change_searxng-engines-blocked.md（2026-10-26）
- Related: [[web-fetch-tool]]
- 設定：omni-agent/searxng/settings.yml
- 參考：`~/gitWrk/hermes-agent/tools/web_tools.py`（`_get_backend` 優先序、web_search 工具描述）
