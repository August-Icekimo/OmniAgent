# Omni-Agent Phase 3.5 — Telegram 通道接入測試清單

> 執行者：Antigravity IDE Agent（HomeLab QA）。Jules 負責實作，不執行測試。但此文件為 HomeLab QA 執行驗證時的參考指南。

## 準備工作 (Pre-requisites)
1. **取得 Telegram Bot Token**：向 `@BotFather` 申請 Bot 並獲取 Token。
2. **取得 Chat ID**：與 Bot 對話後，可呼叫 `https://api.telegram.org/bot<TOKEN>/getUpdates` 取得自己的 `chat_id`。
3. **設定環境變數 (`.env`)**：
   - 填寫 `TELEGRAM_BOT_TOKEN`。
   - 填寫 `TELEGRAM_WEBHOOK_SECRET`（預設：`BYTHESEWORDSIPROTECTMTFAMILY`）。
   - 填寫 `TELEGRAM_ALLOWED_CHAT_IDS`（你的 `chat_id`）。
4. **設定 Webhook**：
   - 如果使用 Caddy 且對外 domain 為 `https://cindy.icekimo.idv.tw`，請執行以下命令通知 Telegram：
     ```bash
     curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
       -H "Content-Type: application/json" \
       -d '{"url":"https://cindy.icekimo.idv.tw/webhook/telegram","secret_token":"BYTHESEWORDSIPROTECTMTFAMILY"}'
     ```
   - 若本地測試可用 `ngrok http 8080` 取得 HTTPS URL 並設定。
5. **啟動 Gateway**：
   ```bash
   podman compose up -d gateway
   ```

---

## 測試項目 (Acceptance Criteria)

### Integration & Setup
- [ ] **I-01 Telegram webhook 設定**：執行 setWebhook 指令後，Telegram API 回傳 `{"ok":true, ...}`。呼叫 `getWebhookInfo` 顯示 `url` 與設定一致。
- [ ] **F-06 變數檢查**：若 Gateway 啟動時有設定 `TELEGRAM_BOT_TOKEN`，log 應包含 `"Telegram webhook handler registered"`。
- [ ] **F-06 變數檢查 (無Token)**：移除 `.env` 中的 `TELEGRAM_BOT_TOKEN` 並重啟，log 應包含 `"TELEGRAM_BOT_TOKEN not set, Telegram webhook disabled"`。呼叫 webhook 時回應 HTTP 503。

### F-01 & F-03 Authentication & Authorization
可以使用 curl 或真正的 Telegram 發送訊息測試。模擬發送指令：
```bash
export TG_SECRET="BYTHESEWORDSIPROTECTMTFAMILY"
export TG_BODY='{"update_id":100001,"message":{"message_id":1,"from":{"id":123456789},"chat":{"id":123456789,"type":"private"},"text":"hello cindy"}}'
curl -s -w "\n%{http_code}\n" -X POST http://localhost:8080/webhook/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: $TG_SECRET" \
  -d "$TG_BODY"
```
- [ ] **F-01-A 合法來源**：帶有正確 `X-Telegram-Bot-Api-Secret-Token` 且 `chat_id` 於名單中，Gateway 回應 `200`。
- [ ] **F-01-B 缺失 Header**：移除 Secret Header 重新發送，Gateway 等待並回應 `401 Unauthorized`。
- [ ] **F-01-C 錯誤 Header**：更換 Secret 內容重新發送，Gateway 回應 `401 Unauthorized`。
- [ ] **F-01-D GET 請求**：發送 `curl -X GET ...`，Gateway 應回覆 `404` 或 Method Not Allowed (`405`)。
- [ ] **F-03-A 未授權的 chat_id**：修改 `$TG_BODY` 內的 `chat.id` 為不再 allowed 清單的值發送。Gateway 回應 `200`，但 log 出現 `"Unauthorized chat_id"`，且資料庫無新訊息寫入。(保護 Bot 免遭公共濫用)。

### F-02 & F-04 訊息轉換與寫入 Queue
- [ ] **F-02-A 處理純文字訊息**：合法發送文字 `"hello cindy"`。檢查 Postgres：
  ```bash
  podman exec -it omni-agent-postgres-1 psql -U omni -d omni_agent -c "SELECT payload FROM message_queue ORDER BY created_at DESC LIMIT 1;"
  ```
  應見 `"platform":"telegram"`, `"message_type":"text"`, `"text":"hello cindy"`, `"user_id":"123456789"`。
- [ ] **F-02-B 忽略非訊息 Update**：發送如 `edited_message` 等 Update (去除 `message` 區塊)，結果回覆 `200` 且 log `"Ignoring non-message update"`，無新 Queue。
- [ ] **F-02-C 圖片訊息**：透過 Telegram 發送單張圖片。結果回覆 `200`，Queue 內的新筆訊息應顯示 `"message_type":"image"`, 且 `"text":""`。

### Non-Functional Requirements
- [ ] **NF-01-A Log 保護**：檢查 `podman logs omni-agent-gateway-1`，確定沒有把 `text` 內容印在 stdout (應只有 JSON structure：method, path, status)。
- [ ] **NF-01-B 敏感字測試**：發送測試訊息文字「MyPassword123」，接著執行 `podman logs omni-agent-gateway-1 | grep MyPassword123`，應**無任何輸出**。
- [ ] **NF-02-A Phase 1-3 相容**：檢查 `/health` 端點，回傳 `{"status":"ok"}`。LINE/BlueBubbles webhook 是否依舊正常運作不報錯。
- [ ] **I-02 StandardMessage 相容**：經過 forwarder 轉發後，在 Brain 端點看到 Telegram 帶來的資料，能進行有效的回覆處理 (Phase 3.5 無需修改 Brain 的 codebase 即可自動相容)。
