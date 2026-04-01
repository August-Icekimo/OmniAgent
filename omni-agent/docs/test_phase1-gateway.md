# Omni-Agent Phase 1 — 人工測試清單
> 跑完所有 ✅ 才可以 merge PR。每個 case 標記 PASS / FAIL / SKIP（附原因）。

---

## 前置準備

```bash
# 1. 複製並填入環境變數
cp .env.example .env
# 必填：
#   LINE_CHANNEL_SECRET=<你的 secret>
#   BLUEBUBBLES_PASSWORD=test_password_123
#   BRAIN_URL 先留空（測試 Brain 缺席情境用）

# 2. 啟動服務
cd omni-agent
podman compose up -d gateway postgres

# 3. 等待健康檢查通過（約 10 秒）
watch -n1 'curl -s http://localhost:8080/health | jq .'

# 快捷別名（省得一直打）
alias psql='podman exec -it omni-agent-postgres-1 psql -U omni -d omni_agent'
alias qlogs='podman logs omni-agent-gateway-1 2>&1 | tail -20 | jq .'
alias qcount='psql -c "SELECT status, count(*) FROM message_queue GROUP BY status ORDER BY status;"'
```

---

## TC-01｜服務啟動與健康檢查

### TC-01-A：正常啟動
```bash
curl -s http://localhost:8080/health | jq .
```
**預期：** `{"status":"ok","queue_depth":0}` HTTP 200

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-B：DB schema 已初始化
```bash
psql -c "\dt"
```
**預期：** 列出 5 個 table：`conversations`、`family_members`、`home_context`、`memory_queue`（或 `message_queue`）、`stress_logs`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-C：Postgres 未就緒時 gateway 等待不崩潰
```bash
# 先停掉 postgres，再啟動 gateway
podman compose stop postgres
podman compose up gateway   # 前景執行，觀察 log
# 預期看到 "DB not ready, retrying in 1s..." 循環，不 exit
# 再啟動 postgres
podman compose up -d postgres
# 預期 gateway 自動連上並繼續服務
```
**預期 log 片段：** `"DB not ready, retrying"`，最終 `"PostgreSQL connected successfully"`

**實際結果：** _______________  **PASS / FAIL**

---

## TC-02｜LINE Webhook

> 先設定一次 BODY 和 SIG 變數，後面各 case 共用 secret

```bash
export LINE_CHANNEL_SECRET="<填你的 secret>"

# 合法 body
export BODY_TEXT='{"destination":"Uxxxxx","events":[{"type":"message","replyToken":"reply001","source":{"userId":"Uabc123","type":"user"},"message":{"type":"text","id":"msg001","text":"hello omni"}}]}'

# 計算合法 signature
export SIG=$(echo -n "$BODY_TEXT" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)
echo "SIG=$SIG"
```

### TC-02-A：合法文字訊息 → 進 queue
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"
```
**預期：** HTTP `200`

```bash
qcount
# 預期：pending | 1
psql -c "SELECT id, payload->>'platform' AS platform, payload->>'user_id' AS user_id, payload->>'text' AS text, status FROM message_queue ORDER BY created_at DESC LIMIT 1;"
# 預期：platform=line, user_id=Uabc123, text=hello omni, status=pending
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-B：錯誤 Signature → 401 拒絕
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: invalidsignatureXXXXXXXXXXX" \
  -d "$BODY_TEXT"
```
**預期：** HTTP `401`，queue 筆數不增加

```bash
qcount  # 數量應與 TC-02-A 後相同
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-C：缺少 Signature header → 401
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -d "$BODY_TEXT"
```
**預期：** HTTP `401`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-D：非訊息 event（follow）→ 靜默忽略
```bash
BODY_FOLLOW='{"destination":"Uxxxxx","events":[{"type":"follow","replyToken":"reply002","source":{"userId":"Uabc999","type":"user"}}]}'
SIG_FOLLOW=$(echo -n "$BODY_FOLLOW" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)

curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG_FOLLOW" \
  -d "$BODY_FOLLOW"
```
**預期：** HTTP `200`，但 queue 筆數不增加

```bash
qcount  # 數量應與前一 case 相同
qlogs   # 應看到 "Ignoring non-message event" debug log
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-E：圖片訊息 → message_type = "image"
```bash
BODY_IMG='{"destination":"Uxxxxx","events":[{"type":"message","replyToken":"reply003","source":{"userId":"Uabc123","type":"user"},"message":{"type":"image","id":"img001"}}]}'
SIG_IMG=$(echo -n "$BODY_IMG" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)

curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG_IMG" \
  -d "$BODY_IMG"

psql -c "SELECT payload->>'message_type' AS msg_type FROM message_queue ORDER BY created_at DESC LIMIT 1;"
```
**預期：** HTTP `200`，`msg_type = image`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-F：回應時間 < 3 秒（LINE timeout 要求）
```bash
time curl -s -o /dev/null -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"
```
**預期：** `real` < `0m3.000s`（通常應 < 100ms）

**實際結果：** _______________  **PASS / FAIL**

---

## TC-03｜BlueBubbles Webhook

### TC-03-A：合法請求 → 進 queue
```bash
BB_BODY='{"type":"new-message","data":{"text":"hi from imessage","chats":[{"chatIdentifier":"+886912345678"}]}}'

curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8080/webhook/bluebubbles?password=test_password_123" \
  -H "Content-Type: application/json" \
  -d "$BB_BODY"
```
**預期：** HTTP `200`

```bash
psql -c "SELECT payload->>'platform' AS platform, payload->>'user_id' AS user_id FROM message_queue ORDER BY created_at DESC LIMIT 1;"
# 預期：platform=imessage, user_id=+886912345678
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-B：錯誤 password → 401
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8080/webhook/bluebubbles?password=wrong_password" \
  -H "Content-Type: application/json" \
  -d "$BB_BODY"
```
**預期：** HTTP `401`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-C：缺少 password → 401
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8080/webhook/bluebubbles" \
  -H "Content-Type: application/json" \
  -d "$BB_BODY"
```
**預期：** HTTP `401`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-D：非新訊息事件 → 靜默忽略
```bash
BB_READ='{"type":"message-read","data":{"guid":"abc"}}'

curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8080/webhook/bluebubbles?password=test_password_123" \
  -H "Content-Type: application/json" \
  -d "$BB_READ"
```
**預期：** HTTP `200`，queue 不增加

**實際結果：** _______________  **PASS / FAIL**

---

## TC-04｜Brain Forwarder

### TC-04-A：BRAIN_URL 未設定 → gateway 正常啟動不 crash
```bash
# compose.yml 中移除或清空 BRAIN_URL，重啟 gateway
podman compose stop gateway
# 在 compose.yml 中確認 BRAIN_URL 未設定，或設為空字串
podman compose up -d gateway

sleep 3
curl -s http://localhost:8080/health | jq .
```
**預期：** gateway 健康，log 含 `"BRAIN_URL is not set"`，不 crash

**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-B：Brain 不存在時 → 訊息保留 queue 不重複消費
> 先確認 BRAIN_URL 設為一個不存在的地址，例如 `http://brain:8000`（brain 容器未啟動）

```bash
# 傳送一筆訊息
curl -s -o /dev/null -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"

# 等 2 秒讓 forwarder 嘗試
sleep 2
qcount
# 預期：failed | N（或 pending，視實作策略）
# 重點：不是 processing（不能卡死）、gateway 沒 crash
podman ps | grep gateway  # 應該仍在 running
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-C：模擬 Brain 在線 → status 改為 done
```bash
# 用 nc 或 python 起一個簡單 HTTP server 模擬 Brain
python3 -m http.server 9999 &
BRAIN_PID=$!

# 修改 compose.yml BRAIN_URL=http://host.containers.internal:9999 然後重啟 gateway
# （或直接用 podman compose 環境變數 override）
podman compose stop gateway
BRAIN_URL=http://host.containers.internal:9999 podman compose up -d gateway

# 送一筆訊息
curl -s -o /dev/null -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"

sleep 2
qcount
# 預期：done | 1（python http server 回 200 html，gateway 視為成功）

kill $BRAIN_PID
```

> ⚠️ `python3 -m http.server` 回的是 HTML，但 gateway forwarder 只檢查 HTTP status code，200 即視為成功。此 case 驗收「status=done 的寫回邏輯」。

**實際結果：** _______________  **PASS / FAIL**

---

## TC-05｜StressManager

### TC-05-A：批次 enqueue 觸發 StressBusy → stress_logs 寫入
```bash
# 快速塞 25 筆假訊息（繞過 gateway，直接 insert）
psql -c "
INSERT INTO message_queue (payload, priority, status)
SELECT
  jsonb_build_object(
    'id', gen_random_uuid(),
    'platform', 'line',
    'user_id', 'Ustress_test',
    'text', 'stress test msg ' || i,
    'message_type', 'text'
  ),
  5,
  'pending'
FROM generate_series(1, 25) AS i;
"

# StressManager 每 30 秒跑一次，等待下一個週期
# 或重啟 gateway 讓 StressManager 立即在啟動後評估一次
echo "等待最多 35 秒..."
sleep 35

psql -c "SELECT level, mood, metrics->>'queue_depth' AS depth, created_at FROM stress_logs ORDER BY created_at DESC LIMIT 3;"
```
**預期：** 至少一筆 `level=StressBusy`（或以上），`mood` 有值（如 "有點忙"），`depth >= 20`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-05-B：塞 55 筆 → StressCritical
```bash
psql -c "
INSERT INTO message_queue (payload, priority, status)
SELECT
  jsonb_build_object('id', gen_random_uuid(), 'platform', 'line', 'user_id', 'Ucritical', 'text', 'critical ' || i, 'message_type', 'text'),
  5, 'pending'
FROM generate_series(1, 55) AS i;
"

sleep 35

psql -c "SELECT level, mood FROM stress_logs ORDER BY created_at DESC LIMIT 1;"
# 預期：level=StressCritical

qlogs | grep -i critical
# 預期：log 出現 error level 的 CRITICAL STRESS LEVEL REACHED
```
**實際結果：** _______________  **PASS / FAIL**

---

## TC-06｜結構化日誌

### TC-06-A：所有 log 輸出為合法 JSON
```bash
podman logs omni-agent-gateway-1 2>&1 | head -20 | while IFS= read -r line; do
  echo "$line" | jq . > /dev/null 2>&1 && echo "OK: $line" || echo "FAIL (not JSON): $line"
done
```
**預期：** 所有行均輸出 `OK:`，無 `FAIL` 行

**實際結果：** _______________  **PASS / FAIL**

---

### TC-06-B：webhook log 不含訊息內容（個資保護）
```bash
# 送一筆包含敏感文字的訊息
SENSITIVE_BODY='{"destination":"U","events":[{"type":"message","replyToken":"r","source":{"userId":"Uprivacy","type":"user"},"message":{"type":"text","id":"s1","text":"我的密碼是 secret123"}}]}'
SIG_S=$(echo -n "$SENSITIVE_BODY" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)

curl -s -o /dev/null -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG_S" \
  -d "$SENSITIVE_BODY"

podman logs omni-agent-gateway-1 2>&1 | grep -i "secret123"
```
**預期：** 無輸出（log 不應出現訊息內容）

**實際結果：** _______________  **PASS / FAIL**

---

## TC-07｜Build 與容器

### TC-07-A：乾淨 build
```bash
cd omni-agent/gateway
go mod tidy
# 預期：無 warning / error

go build ./...
# 預期：build 成功，無 error
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-B：Podman image build
```bash
cd omni-agent/gateway
podman build -t omni-gateway:test .
# 預期：build 成功
podman run --rm omni-gateway:test --help 2>&1 || true
# 預期：能啟動（即使因缺少 env 而退出，不應是 image 損壞）
```
**實際結果：** _______________  **PASS / FAIL**

---

## TC-08｜邊界與錯誤處理

### TC-08-A：GET 打 POST-only endpoint → 405
```bash
curl -s -o /dev/null -w "%{http_code}" -X GET http://localhost:8080/webhook/line
```
**預期：** HTTP `405`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-08-B：畸形 JSON body → 400
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "THIS IS NOT JSON"
```
**預期：** HTTP `400`（或 `401`，端看 signature 驗證先後順序——兩者皆可接受）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-08-C：/health 在 DB 斷線後回 503
```bash
podman compose stop postgres
sleep 2
curl -s http://localhost:8080/health | jq .
```
**預期：** HTTP `503`，body 含 `"db"` 欄位

```bash
# 恢復
podman compose up -d postgres
sleep 5
curl -s http://localhost:8080/health | jq .
# 預期：回到 200 ok
```
**實際結果：** _______________  **PASS / FAIL**

---

## 結果彙總

| TC | 名稱 | 結果 | 備註 |
|---|---|---|---|
| TC-01-A | 正常啟動 | | |
| TC-01-B | Schema 初始化 | | |
| TC-01-C | Postgres 等待不崩潰 | | |
| TC-02-A | LINE 合法訊息進 queue | | |
| TC-02-B | LINE 錯誤 Signature 401 | | |
| TC-02-C | LINE 缺少 Signature 401 | | |
| TC-02-D | LINE follow event 忽略 | | |
| TC-02-E | LINE 圖片 message_type | | |
| TC-02-F | LINE 回應時間 < 3s | | |
| TC-03-A | BB 合法請求進 queue | | |
| TC-03-B | BB 錯誤 password 401 | | |
| TC-03-C | BB 缺少 password 401 | | |
| TC-03-D | BB 非訊息事件忽略 | | |
| TC-04-A | BRAIN_URL 未設定不 crash | | |
| TC-04-B | Brain 不存在訊息不卡死 | | |
| TC-04-C | Brain 在線 status=done | | |
| TC-05-A | StressBusy 觸發寫 log | | |
| TC-05-B | StressCritical 觸發 | | |
| TC-06-A | Log 為合法 JSON | | |
| TC-06-B | Log 不含訊息內容 | | |
| TC-07-A | go build 成功 | | |
| TC-07-B | podman build 成功 | | |
| TC-08-A | GET → 405 | | |
| TC-08-B | 畸形 JSON → 400/401 | | |
| TC-08-C | DB 斷線 → 503 | | |

---

## PR Merge 條件

- **必須全 PASS：** TC-01 / TC-02 / TC-03 / TC-07（核心功能與 build）
- **必須全 PASS：** TC-06-B（個資不外洩——不得妥協）
- **允許 SKIP 並在 PR 說明原因：** TC-04-C（需要額外 mock server 環境）、TC-05（需等 30 秒週期）
- **如有任何 FAIL：** 開 issue 記錄，附上實際輸出，**不** merge

---

*產出：Phase 1 Gateway 人工測試清單 v1.0 | 2026-03-14*
