## 1. Telegram Webhook Implementation

- [x] 1.1 F-01 Telegram Webhook 接收與簽章驗證
  - [x] AC: Given 合法 webhook 請求，when POST `/webhook/telegram`，then Gateway 回應 HTTP `200`。
  - [x] AC: Given 簽章不符或缺失，when 請求到達，then Gateway 回應 HTTP `401`。
- [x] 1.2 F-02 訊息事件解析與 StandardMessage 轉換
  - [x] AC: Given 文字訊息 update，when 解析，then `StandardMessage.platform = "telegram"`。
- [x] 1.3 F-03 陌生 chat_id 身份驗證（白名單機制）
  - [x] AC: Given `TELEGRAM_ALLOWED_CHAT_IDS` 設定，when `chat_id` 在名單內，then 訊息正常進 queue。
  - [x] AC: Given `chat_id` 不在名單內，when 收到 update，then 拒絕寫入 queue 並回應 `200`。

## 2. Queueing & Performance

- [x] 2.1 F-04 訊息寫入 Message Queue
  - [x] AC: Given 合法訊息，when 寫入 queue，then `message_queue` 新增一筆 `status = "pending"`。
- [x] 2.2 F-05 Webhook 回應時間
  - [x] AC: Given 正常狀態，when Telegram 送出 webhook，then Gateway 在 5 秒內回應 HTTP `200`。

## 3. Configuration & Security

- [x] 3.1 F-06 環境變數與設定
  - [x] AC: Given `.env.example`，then 包含 `TELEGRAM_BOT_TOKEN` 等欄位。
- [x] 3.2 NF-01 Log 格式與個資保護
  - [x] AC: Given Telegram webhook 被觸發，then log 為合法 JSON 且不包含訊息內文。
