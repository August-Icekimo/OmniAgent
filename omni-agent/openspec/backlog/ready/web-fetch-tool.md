---
slug: web-fetch-tool
status: done
domain: skills
size: M
priority: P1
created: 2026-11-06
groomed: 2026-11-06
done: 2026-11-06
---

# 讓 Cindy 能打開網頁讀正文（fetch_url 工具）

## Why
`web_search` 只回 title／url／截斷摘要，Cindy 無法打開結果頁。2026-10-29 問「明天新店山區天氣」，
她已搜到中央氣象署鄉鎮預報頁，但摘要沒有逐時數字，只能回「目前無法確認氣溫和降雨機率」——
**查到了但讀不到**，使用者感受等同「找不到資料」。版本頁、公告、CVE 頁等查證類問題同樣卡在這裡。
沙箱雖可連外（`curl` 可用），但工具描述沒教、且輸出 4000 字截斷又是原始 HTML，不是可行路徑。

## What (high-level)
新增一個唯讀工具 `fetch_url`，給定 URL 回傳清理過的正文，讓 Cindy 能「搜尋 → 挑結果 → 讀內容 → 回答」。
設計參考 hermes-agent 的 `web_extract`（`~/gitWrk/hermes-agent/tools/web_tools.py`，2026-11-06 讀）。

**Grooming 定案（2026-11-06，admin）：**
- **正文擷取用 `trafilatura`**（新套件，admin 已核准；離線、免費、去導覽列效果最好）。
- **在 brain 行程內執行**，與 web_search 同層；靠 SSRF 檢查擋內網。
- **JS 動態頁面本次就處理**：靜態抓取後正文過少時，改以 headless Chromium（Playwright）渲染再擷取。
  實測依據：CWA 鄉鎮預報頁 `Town.html?TID=6500600` 靜態 HTML 66KB、`°` 出現 0 次，數字全由 `/Data/js/...` 載入。
  尺寸因此由 S 升為 M。
- **SSRF 防護**：解析 DNS 後擋私網／loopback／link-local／保留段／CGNAT `100.64.0.0/10`（Tailscale，chrysoberyl 即在此段）；
  每一跳 redirect 重新檢查；**headless 瀏覽器的所有子請求也要攔截檢查**（頁面 JS 可能打內網）。URL 內夾帶 secret（`sk-` 等前綴，先 URL-decode）一律擋。
- **預算**：每次呼叫最多 3 個 URL；每頁正文預設 8000 字（ChatGPT 主力 p50 已 30s+，比 hermes 的 15000 保守），
  超出取頭尾並附 footer；回應本體上限 5MB；靜態逾時 15s、渲染逾時 25s。每 turn 次數由既有 `MAX_TOOL_ITERATIONS=5` 兜住。
- **PDF**：`application/pdf` 以既有 `pypdf` 取文字。
- 唯讀、無真實世界副作用 → **不需確認**。

## Acceptance hints
- 重跑「明天新店天氣」：Cindy 搜到氣象署頁面後讀正文（經 JS 渲染），回出具體氣溫／降雨機率
- 一般靜態頁（如 Wikipedia 條目、Linux Mint release notes）不觸發渲染即取得正文，且不超過預算、footer 正確
- `http://postgres:5432`、`http://127.0.0.1`、`http://192.168.x.x`、`http://100.88.136.117`、redirect 到內網、
  渲染頁面中對內網的子請求 → 一律被擋，log 有記錄
- PDF URL 回出文字內容
- 打不開／逾時／正文仍為空 → 回明確錯誤（「頁面打不開」≠「沒有資料」）
- brain 映像檔大小增量與冷啟動延遲記錄於 change doc

## Open questions
（無 — 2026-11-06 grooming 定案）

## Links
- Related spec: openspec/specs/skills/spec.md
- Related: [[web-search-resilience]]（搜尋找得到 → 本卡讀得到）
- 參考：`~/gitWrk/hermes-agent/tools/web_tools.py`（`web_extract_tool`）、`tools/url_safety.py`（`async_is_safe_url`）
