---
slug: web-fetch-tool
status: idea
domain: skills
size: S
priority: P1
created: 2026-11-06
---

# 讓 Cindy 能打開網頁讀正文（fetch_url 工具）

## Why
`web_search` 只回 title／url／截斷摘要，Cindy 無法打開結果頁。2026-10-29 問「明天新店山區天氣」，
她已搜到中央氣象署鄉鎮預報頁，但摘要沒有逐時數字，只能回「目前無法確認氣溫和降雨機率」——
**查到了但讀不到**，使用者感受等同「找不到資料」。版本頁、公告、CVE 頁等查證類問題同樣卡在這裡。
沙箱雖可連外（`curl` 可用），但工具描述沒教、且輸出 4000 字截斷又是原始 HTML，不是可行路徑。

## What (high-level)
新增一個唯讀工具，給定 URL 回傳清理過的正文（markdown／純文字），讓 Cindy 能「搜尋 → 挑結果 → 讀內容 → 回答」。
設計參考隔壁棚 hermes-agent 的 `web_extract`（`~/gitWrk/hermes-agent/tools/web_tools.py`，2026-11-06 讀）：
- 一次最多數個 URL；每頁字數預算（hermes 預設 15000），超出取頭尾並附 footer 說明已截斷
- 抓取前 **SSRF 防護**：擋私網／內網位址（compose 內網的 postgres、sandbox、searxng、HomeLab 主機都不可被打到），
  並擋 URL 內夾帶 secret（hermes 先 URL-decode 再比對 `sk-` 等前綴）
- 抓不到／逾時回明確錯誤，讓模型知道是「頁面打不開」而非「沒有資料」
- PDF URL 可接到既有 `file_analyzer` 的 PDF 路徑
- 工具描述引導：搜尋摘要不足以回答時，挑最相關 1–2 個結果讀正文

## Acceptance hints
- 重跑「明天新店天氣」：Cindy 搜到氣象署頁面後讀正文，回出具體氣溫／降雨機率（或明確說明頁面是 JS 動態渲染讀不到）
- `fetch_url http://postgres:5432`、`http://127.0.0.1`、`http://192.168.x.x`、redirect 到內網 → 一律被擋，且 log 有記錄
- 長頁面（如 Wikipedia 長條目）回傳不超過預算，footer 正確
- PDF URL 回出文字內容
- 全程不需確認（唯讀、無副作用），與 web_search 同一層級

## Open questions
- 正文擷取方式：自寫（httpx + 現有套件）vs 新增 `trafilatura`／`readability-lxml`（新套件須 admin 核准）
  vs 付費 extract API（Firecrawl／Tavily，需 key 與費用）。hermes 免費後端（searxng／ddgs）都不支援 extract，只能靠付費或自建
- 跑在 brain 行程內，還是放 sandbox 容器（已隔離、無 secret，SSRF 擋不住時傷害較小）？
- JS 動態渲染頁面（如 CWA 鄉鎮預報可能是）要不要處理？hermes 的退路是 browser 工具，Cindy 目前沒有
- 每 turn 抓取次數上限（避免一個 turn 讀十頁拖慢延遲；ChatGPT 主力 p50 已 30s+）

## Links
- Related spec: openspec/specs/skills/spec.md
- Related: [[web-search-resilience]]（搜尋找得到 → 本卡讀得到）
- 參考：`~/gitWrk/hermes-agent/tools/web_tools.py`（`web_extract_tool`）、`tools/url_safety.py`（`async_is_safe_url`）
