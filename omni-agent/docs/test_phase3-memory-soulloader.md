# Omni-Agent Phase 3 — 人工測試清單（Memory + SoulLoader）
> 跑完所有 ✅ 才可以 merge PR。每個 case 標記 PASS / FAIL / SKIP（附原因）。
> **執行者：Antigravity IDE Agent（HomeLab QA）**
> **Jules 不執行任何測試。**

---

## 前置準備

```bash
# 1. 確認 .env 已填入
#    ANTHROPIC_API_KEY=<你的 key>
#    POSTGRES_HOST=postgres / POSTGRES_PORT=5432
#    POSTGRES_USER=omni / POSTGRES_PASSWORD=... / POSTGRES_DB=omni_agent
#    BRAIN_URL=http://brain:8000/chat

# 2. 啟動全服務（含 rebuild brain）
cd omni-agent
podman compose up -d --build

# 3. 等待 brain 健康（約 30-60 秒）
watch -n2 'curl -s http://localhost:8000/health | jq .'

# 快捷別名
alias blog='podman logs omni-agent-brain-1 2>&1 | tail -40'
alias bjson='podman logs omni-agent-brain-1 2>&1 | grep "\"module\"" | tail -20 | jq .'
alias psql='podman exec -it omni-agent-postgres-1 psql -U omni -d omni_agent'
alias glog='podman logs omni-agent-gateway-1 2>&1 | tail -20'

# LINE 測試用簽章（與 Phase 1/2 相同）
export LINE_CHANNEL_SECRET="<填你的 LINE_CHANNEL_SECRET>"
export BODY_TEXT='{"destination":"Uxxxxx","events":[{"type":"message","replyToken":"reply001","source":{"userId":"Uabc123","type":"user"},"message":{"type":"text","id":"msg001","text":"hello omni"}}]}'
export SIG=$(echo -n "$BODY_TEXT" | openssl dgst -sha256 -hmac "$LINE_CHANNEL_SECRET" -binary | base64)

# 清空測試資料（每次跑新的測試週期前執行）
psql -c "DELETE FROM conversations; DELETE FROM memory_embeddings; DELETE FROM stress_logs; DELETE FROM home_context WHERE key LIKE 'memory_index:%';"
```

---

## TC-01｜Brain 啟動與模組初始化

### TC-01-A：Brain 正常啟動，SoulLoader 初始化成功
```bash
curl -s http://localhost:8000/health | jq .
```
**預期：** HTTP 200，`{"status":"ok","service":"brain"}`

```bash
blog | grep -E "SoulLoader|DB pool|Brain ready"
```
**預期 log 片段（順序不限）：**
- `"SoulLoader ready"`
- `"DB pool ready"` 或 `"PostgreSQL connected"`
- `"Brain ready."`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-B：DB 無法連線時，Brain 以 stateless 模式啟動
```bash
# 停掉 postgres
podman compose stop postgres
podman compose stop brain
podman compose up -d brain
sleep 15

curl -s http://localhost:8000/health | jq .
blog | grep -E "unavailable|stateless|DB"
```
**預期：** `/health` 回 200（Brain 不崩潰），log 含 `"DB unavailable"` 或 `"stateless mode"`

```bash
# 恢復
podman compose up -d postgres
sleep 5
podman compose stop brain && podman compose up -d brain
```
**實際結果：** _______________  **PASS / FAIL**

---

### TC-01-C：SOUL.md 不存在時，Brain 啟動拋出有意義錯誤
```bash
# 暫時把 SOUL.md 改名
podman exec omni-agent-brain-1 mv /app/../SOUL.md /app/../SOUL.md.bak 2>/dev/null || true
# 注意：SOUL.md 在 brain container 內的路徑依 Dockerfile COPY 決定，確認後調整
podman compose stop brain && podman compose up brain  # 前景跑，看 log

# 預期看到 SoulNotFoundError 或清楚的 FileNotFoundError，不是靜默空字串
# 恢復
podman exec omni-agent-brain-1 mv /app/../SOUL.md.bak /app/../SOUL.md 2>/dev/null || true
podman compose up -d brain
```
**預期：** log 含明確錯誤訊息，不是靜默通過輸出空 system prompt

**實際結果：** _______________  **PASS / FAIL / SKIP**（原因：_______________）

---

## TC-02｜SoulLoader — system prompt 驗證

### TC-02-A：/chat 回覆時 system prompt 包含 SOUL.md 核心內容
> 透過一個特殊問題讓 Cindy 展示人格，驗證 SOUL.md 有被注入。

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "soul-test-01",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "你叫什麼名字？請用你平常說話的方式介紹自己。"
  }' | jq '.reply_text'
```
**預期：** 回覆包含「Cindy」這個名字，語氣符合 SOUL.md §1（像老朋友，不是客服），不出現「您好！我是您的 AI 助理」等官腔。

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-B：stress_logs 有資料時，動態區段注入 system prompt
```bash
# 先插入一筆 StressBusy log
psql -c "INSERT INTO stress_logs (level, mood, metrics, action_taken) VALUES ('StressBusy', '有點忙', '{\"queue_depth\": 25}', '延遲低優先級任務');"

# 等 SoulLoader 下次 render（若有快取，重啟 brain 讓快取刷新）
podman compose stop brain && podman compose up -d brain
sleep 15

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "soul-test-02",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "你最近狀況怎麼樣？"
  }' | jq '.reply_text'
```
**預期：** 回覆反映「有點忙」的狀態感，或提到系統最近忙碌（不需逐字對應，語義符合即可）

```bash
bjson | grep -i "stress\|soul\|render"
# 預期：log 顯示 SoulLoader 有讀取 stress_logs
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-02-C：stress_logs 為空時，Brain 正常運作不崩潰
```bash
psql -c "DELETE FROM stress_logs;"
podman compose stop brain && podman compose up -d brain
sleep 15

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "soul-test-03",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "hi"
  }' | jq '.reply_text'
```
**預期：** HTTP 200，有正常回覆，無 500/502 error

**實際結果：** _______________  **PASS / FAIL**

---

## TC-03｜短期記憶 — 對話歷史持久化

### TC-03-A：/chat 請求後，conversations table 有新記錄
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "mem-test-01",
    "platform": "line",
    "user_id": "Umem123",
    "message_type": "text",
    "text": "我喜歡喝烏龍茶"
  }' | jq '{reply_text, provider}'

sleep 2

psql -c "SELECT user_id, array_length(messages, 1) AS msg_count, created_at FROM conversations WHERE user_id = 'Umem123' ORDER BY created_at DESC LIMIT 1;"
```
**預期：** `user_id=Umem123`，`msg_count=2`（user + assistant 各一筆），`created_at` 為剛才

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-B：多輪對話後，歷史訊息傳給 LLM（跨輪記憶驗證）
```bash
# 第一輪：告訴 Cindy 一件事
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ctx-01",
    "platform": "line",
    "user_id": "Uctx456",
    "message_type": "text",
    "text": "我的名字叫阿明，我是這家的老爸。"
  }' | jq '.reply_text'

sleep 2

# 第二輪：看 Cindy 是否記得
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ctx-02",
    "platform": "line",
    "user_id": "Uctx456",
    "message_type": "text",
    "text": "你還記得我剛才說我叫什麼嗎？"
  }' | jq '.reply_text'
```
**預期：** 第二輪回覆提到「阿明」，證明短期記憶有傳入 LLM context

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-C：conversations 的 log 不含訊息內文（個資保護）
```bash
# 送一筆含敏感文字的訊息
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "privacy-mem-01",
    "platform": "line",
    "user_id": "Uprivacy",
    "message_type": "text",
    "text": "我的信用卡號碼是 1234-5678"
  }' > /dev/null

podman logs omni-agent-brain-1 2>&1 | grep -i "1234"
```
**預期：** 無輸出（log 不包含訊息內容）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-03-D：記憶摘要索引寫入 home_context
```bash
# 確認 conversations 已有 Umem123 的記錄（TC-03-A 之後）
psql -c "SELECT key, value FROM home_context WHERE key LIKE 'memory_index:%' LIMIT 5;"
```
**預期：** 至少一筆 `key=memory_index:Umem123`，`value` 為 JSONB 陣列，各條目 ≤150 字

**實際結果：** _______________  **PASS / FAIL**

---

## TC-04｜長期記憶 — pgvector Embedding

### TC-04-A：/chat 後，memory_embeddings 有新向量
```bash
# 使用 TC-03-A 的 Umem123，等非同步 embedding 完成（最多 15 秒）
sleep 15

psql -c "SELECT user_id, length(content) AS content_len, vector_dims(embedding) AS dims, created_at FROM memory_embeddings WHERE user_id = 'Umem123' ORDER BY created_at DESC LIMIT 3;"
```
**預期：** `dims=1536`，`user_id=Umem123`，`content_len > 0`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-B：語意召回 — 相關記憶能被檢索到
```bash
# 先確保 TC-04-A 的 embedding 已寫入（Umem123 說過「喜歡喝烏龍茶」）
# 測試語意相近的查詢是否能召回

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "recall-01",
    "platform": "line",
    "user_id": "Umem123",
    "message_type": "text",
    "text": "你知道我喜歡喝什麼飲料嗎？"
  }' | jq '.reply_text'
```
**預期：** 回覆提到「烏龍茶」（從長期記憶召回），或 log 顯示有召回相關記憶

```bash
bjson | grep -i "recall\|memory\|embedding"
# 預期：log 顯示 long_term recall 被觸發
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-C：無相關記憶時，/chat 正常運作不注入雜訊
```bash
# 使用全新 user_id，memory_embeddings 無歷史
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "recall-new-01",
    "platform": "line",
    "user_id": "Ubrandnew999",
    "message_type": "text",
    "text": "你好"
  }' | jq '{reply_text, provider}'
```
**預期：** HTTP 200，正常回覆，無奇怪的記憶注入痕跡

**實際結果：** _______________  **PASS / FAIL**

---

### TC-04-D：Embedding API 失敗時，/chat 仍正常回覆
```bash
# 暫時設定錯誤的 API key，讓 embedding 失敗
podman compose stop brain
ANTHROPIC_API_KEY="sk-invalid-key-test" podman compose up -d brain
sleep 20

curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "embed-fail-01",
    "platform": "line",
    "user_id": "Ufailtest",
    "message_type": "text",
    "text": "測試"
  }'

# 恢復正常 API key
podman compose stop brain && podman compose up -d brain
```
**預期：** `/chat` 回 200（不是 502），embedding 失敗只在 log 記錄 error，不 block 回覆

**實際結果：** _______________  **PASS / FAIL**

---

## TC-05｜StressManager — 日記寫入補完驗證

### TC-05-A：StressBusy 寫入含 mood 和 action_taken
```bash
# 清空 stress_logs
psql -c "DELETE FROM stress_logs;"

# 插入 25 筆 pending 訊息
psql -c "
INSERT INTO message_queue (payload, priority, status)
SELECT jsonb_build_object('id', gen_random_uuid(), 'platform', 'line', 'user_id', 'Ustress', 'text', 'msg ' || i, 'message_type', 'text'), 5, 'pending'
FROM generate_series(1, 25) AS i;
"

# 等 StressManager 週期（最多 35 秒）
sleep 35

psql -c "SELECT level, mood, action_taken, metrics->>'queue_depth' AS depth FROM stress_logs ORDER BY created_at DESC LIMIT 1;"
```
**預期：** `level=StressBusy`，`mood` 為非空中文字串，`action_taken` 非空，`depth >= 20`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-05-B：StressCritical 寫入含完整欄位
```bash
psql -c "DELETE FROM message_queue WHERE status = 'pending'; DELETE FROM stress_logs;"

psql -c "
INSERT INTO message_queue (payload, priority, status)
SELECT jsonb_build_object('id', gen_random_uuid(), 'platform', 'line', 'user_id', 'Ucritical', 'text', 'critical ' || i, 'message_type', 'text'), 5, 'pending'
FROM generate_series(1, 55) AS i;
"

sleep 35

psql -c "SELECT level, mood, action_taken FROM stress_logs ORDER BY created_at DESC LIMIT 1;"
```
**預期：** `level=StressCritical`，`mood` 非空，`action_taken` 非空

**實際結果：** _______________  **PASS / FAIL**

---

### TC-05-C：StressCalm 不寫 stress_logs
```bash
psql -c "DELETE FROM message_queue; DELETE FROM stress_logs;"

# queue 為空，等一個週期
sleep 35

psql -c "SELECT count(*) FROM stress_logs;"
```
**預期：** `count = 0`（Calm 不寫日記）

```bash
glog | grep -i "calm\|stress"
# 預期：gateway log 有 "StressCalm" 的 INFO log，但不寫 DB
```

**實際結果：** _______________  **PASS / FAIL**

---

## TC-06｜端到端整合 — Gateway → Brain → Memory

### TC-06-A：LINE webhook → queue → brain 回覆 → conversations 寫入
```bash
psql -c "DELETE FROM conversations WHERE user_id = 'Uabc123';"

curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/webhook/line \
  -H "Content-Type: application/json" \
  -H "X-Line-Signature: $SIG" \
  -d "$BODY_TEXT"

sleep 8

# 確認 queue 已處理
psql -c "SELECT status FROM message_queue ORDER BY created_at DESC LIMIT 1;"
# 預期：done

# 確認 conversations 有記錄
psql -c "SELECT user_id, array_length(messages, 1) AS msg_count FROM conversations WHERE user_id = 'Uabc123' ORDER BY created_at DESC LIMIT 1;"
# 預期：user_id=Uabc123, msg_count=2
```

**實際結果：** _______________  **PASS / FAIL**

---

### TC-06-B：stress_logs 資料透過 SoulLoader 影響 Cindy 回覆語氣
```bash
# 插入一筆 StressCritical log
psql -c "INSERT INTO stress_logs (level, mood, metrics, action_taken) VALUES ('StressCritical', '系統快崩潰了', '{\"queue_depth\": 60}', '強制熔斷');"

# 重啟 brain 讓快取刷新
podman compose stop brain && podman compose up -d brain
sleep 20

curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "e2e-stress-01",
    "platform": "line",
    "user_id": "Uabc123",
    "message_type": "text",
    "text": "最近系統還好嗎？"
  }' | jq '.reply_text'
```
**預期：** 回覆語氣反映系統壓力（如「最近有點忙」、「queue 積了一堆」等），符合 SOUL.md §3 過載行為模式

**實際結果：** _______________  **PASS / FAIL**

---

## TC-07｜日誌品質

### TC-07-A：Brain 業務 log 為合法 JSON
```bash
podman logs omni-agent-brain-1 2>&1 | grep '"module"' | while IFS= read -r line; do
  echo "$line" | jq . > /dev/null 2>&1 && echo "OK" || echo "FAIL: $line"
done
```
**預期：** 全部輸出 `OK`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-B：log 不含訊息內文（個資保護——不得妥協）
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "log-privacy-01",
    "platform": "line",
    "user_id": "Uprivacy2",
    "message_type": "text",
    "text": "我的密碼是 hunter2 銀行帳號 0912345678"
  }' > /dev/null

podman logs omni-agent-brain-1 2>&1 | grep -E "hunter2|0912345678"
```
**預期：** 無輸出

**實際結果：** _______________  **PASS / FAIL**

---

### TC-07-C：embedding log 不含 content 明文
```bash
sleep 15  # 等 TC-07-B 的 embedding 任務完成

podman logs omni-agent-brain-1 2>&1 | grep -i "embedding" | tail -5 | jq .
# 預期：log 含 user_id、dims、耗時，不含 content 明文
podman logs omni-agent-brain-1 2>&1 | grep "hunter2"
# 預期：無輸出
```

**實際結果：** _______________  **PASS / FAIL**

---

## TC-08｜效能基準

### TC-08-A：/chat 回應時間合理（記憶召回 + SoulLoader 不顯著增加延遲）
```bash
# 確保 Umem123 有 embedding 記錄（TC-04-A 之後）
time curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "perf-phase3-01",
    "platform": "line",
    "user_id": "Umem123",
    "message_type": "text",
    "text": "快速測試"
  }' | jq '.reply_text'
```
**預期：** `real` < `0m35.000s`（LLM 呼叫本身佔大部分時間，記憶操作不應超過 1 秒額外開銷）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-08-B：memory_embeddings 100 筆時，recall 完成時間 < 500ms
```bash
# 插入 100 筆測試 embedding（直接插 DB，不走 API）
psql -c "
INSERT INTO memory_embeddings (user_id, content, embedding)
SELECT
  'Uperftest',
  'test content ' || i,
  ('[' || array_to_string(array(SELECT (random() * 2 - 1)::text FROM generate_series(1, 1536)), ',') || ']')::vector
FROM generate_series(1, 100) AS i;
"

# 觸發一次帶 recall 的 /chat
time curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "id": "perf-recall-01",
    "platform": "line",
    "user_id": "Uperftest",
    "message_type": "text",
    "text": "test query"
  }' | jq '{reply_text}' > /dev/null
```
**預期：** `real` < `0m35.000s`；bjson 中 recall 操作耗時 < 500ms

**實際結果：** _______________  **PASS / FAIL**

---

## TC-09｜Build 驗收

### TC-09-A：brain 乾淨 build
```bash
podman build -t omni-brain:phase3-test ./brain
```
**預期：** build 成功，無 error（warning 可接受）

**實際結果：** _______________  **PASS / FAIL**

---

### TC-09-B：Phase 1 Gateway 不受影響
```bash
curl -s http://localhost:8080/health | jq .
```
**預期：** HTTP 200，`{"status":"ok","queue_depth":<數值>}`

**實際結果：** _______________  **PASS / FAIL**

---

### TC-09-C：Phase 2 /chat 基本功能不退步
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"id":"regression-01","platform":"line","user_id":"Ureg","message_type":"text","text":"1+1等於多少？"}' \
  | jq '{reply_text, provider, cached}'
```
**預期：** HTTP 200，`reply_text` 非空，`provider` 為有效值

**實際結果：** _______________  **PASS / FAIL**

---

## 結果彙總

| TC | 名稱 | 結果 | 備註 |
|---|---|---|---|
| TC-01-A | Brain 啟動 SoulLoader 初始化 | | |
| TC-01-B | DB 無法連線 stateless 模式 | | |
| TC-01-C | SOUL.md 不存在拋有意義錯誤 | | |
| TC-02-A | system prompt 包含 SOUL.md 人格 | | |
| TC-02-B | stress_logs 動態注入 prompt | | |
| TC-02-C | stress_logs 為空不崩潰 | | |
| TC-03-A | conversations table 寫入 | | |
| TC-03-B | 跨輪對話記憶（短期） | | |
| TC-03-C | log 不含訊息內文（個資） | | |
| TC-03-D | 記憶摘要索引寫 home_context | | |
| TC-04-A | memory_embeddings 向量寫入 | | |
| TC-04-B | 語意召回正確 | | |
| TC-04-C | 無記憶時正常運作 | | |
| TC-04-D | Embedding API 失敗不 block /chat | | |
| TC-05-A | StressBusy 含 mood + action_taken | | |
| TC-05-B | StressCritical 含完整欄位 | | |
| TC-05-C | StressCalm 不寫 stress_logs | | |
| TC-06-A | 端到端 LINE→Brain→conversations | | |
| TC-06-B | stress_logs 影響 Cindy 語氣 | | |
| TC-07-A | Brain log 為合法 JSON | | |
| TC-07-B | log 不含訊息內文（不得妥協） | | |
| TC-07-C | embedding log 不含 content 明文 | | |
| TC-08-A | /chat 回應時間合理 | | |
| TC-08-B | recall 100 筆 < 500ms | | |
| TC-09-A | brain image build 成功 | | |
| TC-09-B | Phase 1 gateway 不受影響 | | |
| TC-09-C | Phase 2 /chat 不退步 | | |

---

## PR Merge 條件

**必須全 PASS（不得妥協）：**
- TC-01-A（服務啟動）
- TC-02-A（SOUL.md 人格注入）
- TC-03-A、TC-03-B（短期記憶基本功能）
- TC-03-C、TC-07-B（個資保護——絕對不妥協）
- TC-04-A（embedding 寫入）
- TC-09-A、TC-09-B、TC-09-C（Build + 不退步）

**允許 SKIP 並在 PR 說明原因：**
- TC-01-C（需手動在容器內操作 SOUL.md）
- TC-04-B（語意召回需要充足的測試資料量）
- TC-04-D（需臨時改 API key，環境操作複雜）
- TC-08-B（需手動插入 100 筆 fake embedding）

**如有任何 FAIL：** 開 issue 記錄，附實際輸出，**不** merge。

---

*產出：Phase 3 Memory + SoulLoader 人工測試清單 v1.0 | 2026-04-05*
