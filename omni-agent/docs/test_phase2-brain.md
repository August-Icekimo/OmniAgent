# Omni-Agent Phase 2 — 人工測試清單（Brain）
> 跑完所有 ✅ 才可以 merge PR。每個 case 標記 PASS / FAIL / SKIP（附原因）。

---

## 前置準備

```bash
# 1. 填入 API Keys（至少需要 ANTHROPIC_API_KEY）
#    在 omni-agent/.env 確認以下欄位已填寫：
#      ANTHROPIC_API_KEY=<你的 key>
#      GEMINI_API_KEY=<你的 key>（可選，不填則 Gemini provider 不啟用）

# 2. 啟動全服務（postgres + gateway + brain）
cd omni-agent
podman compose up -d --build

# 3. 等待 brain 健康（約 30-60 秒，pip install 需要時間）
watch -n2 'curl -s http://localhost:8000/health | jq .'

# 快捷別名
alias blog='podman logs omni-agent-brain-1 2>&1 | tail -30 | jq .'
alias glog='podman logs omni-agent-gateway-1 2>&1 | tail -20 | jq .'
alias psql='podman exec -it omni-agent-postgres-1 psql -U omni -d omni_agent'

# 測試用 LINE 簽章（與 Phase 1 相同，需填入 secret）
export LINE_CHANNEL_SECRET="<填你的 LINE_CHANNEL_SECRET>"
export BODY_TEXT='{"destination":"Uxxxxx","events":[{"type":"message","replyToken":"reply001","source":{"userId":"Uabc123","type":"user"},"message":{"type":"text","id":"msg001","text":"hello omni"}}]}'
export SIG=$(echo -n "$BODY_TEXT" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)
```

---

## TC-01｜Brain 服務啟動與健康檢查

### TC-01-A：Brain 正常啟動
```bash
curl -s http://localhost:8000/health | jq .
```
**預期：** `{"status":"ok","service":"brain"}` HTTP 200

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-B：啟動 log 顯示已啟用的 provider
```bash
blog | grep -E "provider|Brain"
```
**預期 log 片段（依 .env 設定而異）：**
- 有 ANTHROPIC_API_KEY → `"Claude provider enabled (default)"`
- 有 GEMINI_API_KEY → `"Gemini provider enabled"`
- 兩者皆無 → `"No LLM providers configured! Set API keys in .env"`（此時應 FAIL）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-C：Brain image build 無 error
```bash
podman build -t omni-brain:test ./brain
```
**預期：** build 成功，無 error（warning 可接受）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-D：Brain 無 API key 時正常啟動（不 crash）
```bash
# 暫時移除 ANTHROPIC_API_KEY 再啟動
podman compose stop brain
ANTHROPIC_API_KEY="" podman compose up -d brain
sleep 10
curl -s http://localhost:8000/health | jq .
# 恢復
podman compose stop brain
podman compose up -d brain
```
**預期：** `/health` 仍回 200，log 含 `"No LLM providers configured"`，Brain 不 crash

**實際結果：** _______________  **PASS / FAIL**

---

## TC-02｜/chat 端點 — 基本功能

### TC-02-A：合法文字訊息 → 取得 LLM 回覆
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-001",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "你好，請用一句話介紹你自己"
  }' | jq .
```
**預期：** HTTP 200，body 含：
```json
{
  "reply_text": "<非空字串>",
  "model_used": "<模型名稱，如 claude-sonnet-4-20250514>",
  "provider": "claude",
  "cached": false
}
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-B：空 text → 400 拒絕
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-002",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": ""
  }'
```
**預期：** HTTP `400`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-C：text 為 null（省略欄位） → 400
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-003",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "image"
  }'
```
**預期：** HTTP `400`（`text` 為 null，Brain 拒絕）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-D：畸形 JSON body → 422
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d 'THIS IS NOT JSON'
```
**預期：** HTTP `422`（FastAPI Pydantic validation error）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-E：缺少必填欄位 → 422
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```
**預期：** HTTP `422`（缺少 `id`, `platform`, `user_id`, `message_type`）

**實際結果：** _______________  **PASS / FAIL**

---

## TC-03｜ModelRouter — Provider 路由

### TC-03-A：預設 provider 為 claude（有 ANTHROPIC_API_KEY 時）
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-router-01",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "say hi"
  }' | jq '.provider'
```
**預期：** `"claude"`

```bash
blog | grep "Routing to provider"
# 預期 log：Routing to provider: claude (claude-sonnet-4-20250514)
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-B：僅設 GEMINI_API_KEY（無 ANTHROPIC_API_KEY）→ fallback 到 gemini
```bash
# 停 brain，以僅 GEMINI_API_KEY 重啟
podman compose stop brain
ANTHROPIC_API_KEY="" podman compose up -d brain
sleep 10

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-router-02",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "say hi"
  }' | jq '.provider'

# 恢復
podman compose stop brain
podman compose up -d brain
```
**預期：** `"gemini"`（ModelRouter fallback 到第一個可用 provider）

> ⚠️ 此 case 需要 `GEMINI_API_KEY` 已設定。GEMINI_API_KEY 也未設 → 預期 HTTP 502（無可用 provider）。

**實際結果：** _______________  **PASS / FAIL / SKIP**（原因：_______________）

---

### TC-03-C：所有 provider key 皆空 → /chat 回 502
```bash
podman compose stop brain
ANTHROPIC_API_KEY="" GEMINI_API_KEY="" podman compose up -d brain
sleep 10

curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "test-router-03",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "hello"
  }'

# 恢復
podman compose stop brain
podman compose up -d brain
```
**預期：** HTTP `502`，log 含 `"No LLM providers registered"`

**實際結果：** _______________  **PASS / FAIL**

---

## TC-04｜Prompt Caching — 成本監控

### TC-04-A：連續兩次相同 prompt → 第二次 cached=true（Claude）
> 此 case 需要 `ANTHROPIC_API_KEY` 設定，且 system prompt 夠長（≥1024 tokens）才會觸發 cache。  
> Phase 2 的 `system_prompt` 目前為 `null`，因此 `cached` 預期仍為 `false`。  
> 此 case 驗收「`cached` 欄位正確回傳，不拋 error」。

```bash
# 第一次
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"id":"cache-01","platform":"line","user_id":"U1","message_type":"text","text":"什麼是光合作用？"}' \
  | jq '{provider, cached, model_used}'

# 第二次（相同內容）
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"id":"cache-02","platform":"line","user_id":"U1","message_type":"text","text":"什麼是光合作用？"}' \
  | jq '{provider, cached, model_used}'
```
**預期：** 兩次都回 HTTP 200；`cached` 欄位為 `false`（Phase 2 尚無 system prompt，cache 不會觸發）；`model_used` 為 claude-sonnet-4-* 系列。

**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-B：usage 欄位出現在 log（token 計費監控）
```bash
blog | grep -i "Routing to provider"
```
**預期：** 每次 /chat 請求都有 `"Routing to provider: claude"` log，不報 error

**實際結果：** _______________  **PASS / FAIL**

---

## TC-05｜Gateway ↔ Brain 端到端整合

> 此測試組驗收 Gateway 能正確將訊息轉給 Brain，Brain 回覆後 queue status 改為 done。  
> **前提：** gateway 和 brain 都已啟動，`BRAIN_URL=http://brain:8000` 已設定在 .env。

### TC-05-A：LINE webhook → gateway queue → brain 回覆 → status=done
```bash
# 傳送 LINE 訊息到 gateway
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8086/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"

# 等 forwarder 處理（約 2-5 秒）
sleep 5

# 確認 queue 狀態
psql -c "SELECT id, payload->>'text' AS text, status FROM message_queue ORDER BY created_at DESC LIMIT 1;"
```
**預期：**
- `curl` 回 HTTP `200`（gateway 立即回應）
- queue 最新一筆 `status = done`
- `blog` 可見 `"Routing to provider: claude"`

```bash
blog | tail -10 | jq .
glog | tail -10 | jq .
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-05-B：Brain 回覆時間合理（< 30 秒）
```bash
# 先清 queue（避免積壓影響計時）
psql -c "DELETE FROM message_queue;"

time curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"id":"perf-01","platform":"line","user_id":"U1","message_type":"text","text":"用一句話描述台灣"}' \
  | jq '.reply_text'
```
**預期：** `real` < `0m30.000s`（LLM API 正常情況下應 3-10 秒）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-05-C：Brain 短暫掉線後 gateway 訊息重試不爆炸
```bash
# 停 brain
podman compose stop brain

# 送一筆訊息到 gateway
curl -s -o /dev/null -X POST http://localhost:8086/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"

sleep 3
psql -c "SELECT status, count(*) FROM message_queue GROUP BY status;"
# 預期：failed 或 pending（不是 processing 卡死）

# 重啟 brain
podman compose up -d brain
sleep 15

# gateway 確認仍在跑
curl -s http://localhost:8086/health | jq .
```
**預期：** gateway 不 crash，queue 不卡死在 `processing`；brain 恢復後 gateway log 不報 panic

**實際結果：** _______________  **PASS / FAIL**

---

## TC-06｜結構化日誌

### TC-06-A：Brain log 輸出為合法 JSON
```bash
podman logs omni-agent-brain-1 2>&1 | grep -v "^INFO\|^WARNING\|^ERROR" | head -20 | while IFS= read -r line; do
  echo "$line" | jq . > /dev/null 2>&1 && echo "OK: $line" || echo "FAIL (not JSON): $line"
done
```
> ⚠️ uvicorn 本身的 access log 格式不是 JSON（如 `INFO: ... 200 OK`），這些行可忽略。  
> 只驗收 `brain` logger 的業務 log（含 `"module":"brain"` 的行）。

```bash
podman logs omni-agent-brain-1 2>&1 | grep '"module":"brain"' | while IFS= read -r line; do
  echo "$line" | jq . > /dev/null 2>&1 && echo "OK" || echo "FAIL: $line"
done
```
**預期：** 所有業務 log 均輸出 `OK`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-06-B：cache HIT 時 log 記錄省下的 tokens
> Phase 2 system_prompt 為 null，cache 不會觸發。此 case 驗收「cache HIT log 格式正確」——  
> 可手動呼叫 ClaudeClient 帶長 system_prompt 觸發，或留待 Phase 3 SoulLoader 完成後再驗收。

```bash
# 若 cache 有被觸發，log 應含：
blog | grep "Cache HIT"
# 預期片段：{"msg":"Cache HIT on claude — saved tokens: 800"}
```
**預期：** 若有 cache HIT，log 含 `tokens` 數值

**實際結果：** _______________  **PASS / FAIL / SKIP**（原因：Phase 2 system_prompt 為 null，cache 不觸發）

---

## TC-07｜Build 與容器驗收

### TC-07-A：brain requirements.txt 包含所有必要套件
```bash
grep -E "anthropic|google-genai|openai|fastapi|uvicorn" brain/requirements.txt
```
**預期：** 5 個關鍵套件都出現

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-B：compose.yml 包含 brain service，不含 litellm/router service
```bash
grep -E "brain:|litellm:|router:" compose.yml
```
**預期：** 輸出只有 `brain:`（無 `litellm:` 或 `router:`）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-C：brain/llm/ 目錄包含 6 個必要檔案
```bash
ls brain/llm/
```
**預期：** `__init__.py  base.py  claude_client.py  gemini_client.py  local_client.py  router.py`（共 6 個）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-D：router/ 目錄已刪除
```bash
ls router/ 2>&1
```
**預期：** `ls: cannot access 'router/': No such file or directory`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-E：Phase 1 Gateway 不受影響
```bash
curl -s http://localhost:8086/health | jq .
```
**預期：** HTTP 200，`{"status":"ok","queue_depth":<數值>}`

```bash
glog | tail -5 | jq .
# 預期：無 error，gateway 正常運作
```

**實際結果：** _______________  **PASS / FAIL**

---

## TC-08｜邊界與錯誤處理

### TC-08-A：GET 打 /chat（POST-only）→ 405
```bash
curl -s -o /dev/null -w "%{http_code}" -X GET http://localhost:8000/chat
```
**預期：** HTTP `405`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-08-B：超長訊息（>10000 字元）→ 正常處理或回 502
```bash
LONG_TEXT=$(python3 -c "print('測試' * 5000)")
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"long-01\",\"platform\":\"line\",\"user_id\":\"U1\",\"message_type\":\"text\",\"text\":\"$LONG_TEXT\"}"
```
**預期：** HTTP `200` 或 `502`（LLM 拒絕超長 input）；不得是 500（Brain 自身崩潰）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-08-C：OpenAPI 文件可存取
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/openapi.json
```
**預期：** 兩者皆 HTTP `200`

**實際結果：** _______________  **PASS / FAIL**

---

## 結果彙總

| TC | 名稱 | 結果 | 備註 |
|---|---|---|---|
| TC-01-A | Brain 正常啟動 | | |
| TC-01-B | 啟動 log 顯示 provider | | |
| TC-01-C | Brain image build | | |
| TC-01-D | 無 API key 不 crash | | |
| TC-02-A | /chat 合法文字訊息 | | |
| TC-02-B | 空 text → 400 | | |
| TC-02-C | text=null → 400 | | |
| TC-02-D | 畸形 JSON → 422 | | |
| TC-02-E | 缺必填欄位 → 422 | | |
| TC-03-A | 預設 provider=claude | | |
| TC-03-B | 無 Claude 時 fallback Gemini | | |
| TC-03-C | 全無 key → 502 | | |
| TC-04-A | cached 欄位正確回傳 | | |
| TC-04-B | usage log 出現 | | |
| TC-05-A | Gateway→Brain 端到端 | | |
| TC-05-B | Brain 回覆 < 30s | | |
| TC-05-C | Brain 掉線 gateway 不爆炸 | | |
| TC-06-A | Brain log 為合法 JSON | | |
| TC-06-B | Cache HIT log 格式 | | |
| TC-07-A | requirements.txt 完整 | | |
| TC-07-B | compose.yml brain 無 litellm | | |
| TC-07-C | brain/llm/ 6 個檔案 | | |
| TC-07-D | router/ 目錄已刪除 | | |
| TC-07-E | Phase 1 gateway 不受影響 | | |
| TC-08-A | GET /chat → 405 | | |
| TC-08-B | 超長訊息不 crash | | |
| TC-08-C | /docs 可存取 | | |

---

## PR Merge 條件

- **必須全 PASS：** TC-01-A、TC-01-C、TC-02-A、TC-02-B、TC-02-D、TC-07-A～TC-07-E（Build + 基本功能）
- **必須全 PASS：** TC-03-A、TC-05-A（Provider 路由 + 端到端整合）
- **允許 SKIP 並在 PR 說明原因：**
  - TC-03-B（需關閉 ANTHROPIC_API_KEY 才能測試 Gemini fallback）
  - TC-04-B/TC-06-B（cache 需 system prompt，Phase 3 SoulLoader 完成後再驗收）
  - TC-05-C（需手動模擬斷線環境）
- **如有任何 FAIL：** 開 issue 記錄，附上實際輸出，**不** merge

---

*產出：Phase 2 Brain 人工測試清單 v1.0 | 2026-04-04*
