# Omni-Agent — 工程憲法 (Engineering Constitution)
> 本文件是給實作 Agent（Antigravity）的核心指引。
> 在開始任何 Phase 的實作前，必須完整理解此文件的每一項決策與其背後理由。

---

## 0. 專案定位

**Omni-Agent** 是一個部署於 HomeLab 的家庭專屬多模態 AI 助理，
目標角色是**家庭服務員 / 家族總管**，服務對象是整個家庭，而非單一用戶。

部署環境：
- **Synology DSM** + Container Manager（Security Gateway）
  - **Front-door**: 處理外部真實網路流量 (Realnetwork Traffic)
  - **Caddy**: 反向代理 + Coraza WAF (Web Application Firewall)
  - **CrowdSec**: 全球聯防威脅隔離
  - **Guacamole**: 專屬遠端自動化管理入口
- **Debian 13** + Podman 容器（主力運算節點）
  - **The Senses**: Go API Gateway
  - **The Brain**: Python FastAPI + LangGraph
  - **The Hippocampus**: PostgreSQL + pgvector
- **Mac Mini M4** + mlx-lm（本地 LLM 推論核心，OpenAI-compatible API）

---

## 1. 系統架構：三層架構

```
真實網路 (External World)
  │  HTTPS (443) / LINE Webhook / iMessage
  ▼
┌─────────────────────────────────────────┐
│  Security Gateway (Synology DSM)        │
│  · Caddy + Coraza WAF (流量過濾)         │
│  · CrowdSec (IP 封鎖與威脅情資)          │
│  · Guacamole (管理入口)                  │
└───────────────┬─────────────────────────┘
                │ Proxy Pass (Internal Network)
                ▼
┌─────────────────────────────────────────┐
│  The Senses — Go API Gateway (Debian)   │
│  · 接收並驗證 Webhook 簽章              │
│  · 統一轉換為 StandardMessage{}         │
│  · 非同步回覆（應對 LINE 3 秒 timeout） │
│  · 內建 StressManager 小腦袋機制        │
└───────────────┬─────────────────────────┘
                │ HTTP (StandardMessage JSON)
                ▼
┌─────────────────────────────────────────┐
│  The Brain — Python FastAPI + LangGraph │
│  · 對話狀態管理（LangGraph stateful）   │
│  · SoulLoader：組裝 system prompt       │
│  · ModelRouter：原廠 SDK 智慧路由       │
│    ├─ Claude (anthropic SDK + cache)    │
│    ├─ Gemini (google-genai SDK + cache) │
│    └─ Local MLX (openai SDK → Mac Mini) │
│  · MCP Skills 呼叫                      │
│  · RAG 記憶檢索（pgvector）             │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  The Hippocampus — PostgreSQL（唯一 DB） │
│  · pgvector：長期語意記憶               │
│  · SKIP LOCKED：Message Queue           │
│  · LISTEN/NOTIFY：即時推送              │
│  · JSONB：家庭資料、設備狀態            │
│  · stress_logs：小腦袋日記              │
└─────────────────────────────────────────┘
```

---

## 2. 核心工程哲學決策（不可推翻）

### 2.1 PostgreSQL 是唯一資料層

**決策：** 用 PostgreSQL 替換所有獨立資料服務。

| 原始元件 | 替換方案 | 替換理由 |
|---|---|---|
| SQLite | pg: conversations table | 避免 write lock，統一管理 |
| ChromaDB | pg: pgvector extension | 省去獨立容器，家庭用量完全足夠 |
| Redis Queue | pg: SKIP LOCKED + LISTEN/NOTIFY | 消除額外依賴，訊息本體持久化 |

**收益：**
- 單一備份指令：`pg_dump omni_agent` 涵蓋所有狀態
- 單一監控對象
- Podman pod 減少兩個容器

**已知取捨（接受）：**
- Queue 高頻場景（>數百/秒）效能不如 Redis，但 HomeLab 用量永遠不會觸及此上限
- `LISTEN/NOTIFY` 無消息持久化，但因訊息本體在 table 中，重啟後 poll 可恢復

### 2.2 SOUL.md 維持 Markdown，FAMILY 資料進 PostgreSQL

**決策：** 雙層人格架構

```
SOUL.md (git 管理，Markdown)
  └─ 人格核心、價值觀、語氣規則、邊界定義
     → 不常變動，需要版本控制，LLM 理解最佳

PostgreSQL family_members + home_context (JSONB)
  └─ 家庭成員資料、權限層級、設備資訊、偏好設定
     → 需要動態更新、程式化存取、細粒度授權

soul/loader.py
  └─ 讀取 SOUL.md + 查詢 PostgreSQL
     → 動態渲染 Markdown system prompt → 注入 LLM
```

**關鍵理由：** LLM 對 Markdown 格式的指令遵從率高於 JSON。JSON 對機器友善，對 LLM 是資料掃描而非行為內化。

**嚴禁：** 直接把 JSON 或 SQL 查詢結果作為 system prompt 餵給 LLM。

### 2.3 小腦袋（StressManager）— 過載自我感知機制

**決策：** Go Gateway 層內建自適應壓力感知器，有兩種應對策略。

**壓力指標：**
```go
type StressMetrics struct {
    QueueDepth        int
    QueueGrowthRate   float64       // 趨勢比絕對值更重要
    P95ProcessingTime time.Duration // 感受最真實的指標
    ErrorRate         float64
    ActiveUsers       int
}
```

**壓力等級：**
```
StressCalm     → 正常運作
StressBusy     → 輕微降級 + 告知用戶「稍等」
StressOverload → 二擇一策略（見下）
StressCritical → 強制熔斷 + 主帳號警報
```

**兩種策略（非二選一，有優先順序）：**

- **策略 A — 抱怨與寫日記（Graceful Degradation）：**
  費用敏感或任務不緊急時，回覆帶有個性的等待訊息，延遲低優先級任務，將過載事件寫入 `stress_logs`（JSONB，含 mood 欄位）。

- **策略 B — 老闆加錢（Model Escalation）：**
  任務重要或用戶等不了時，透過 ModelRouter 切換更強模型，依 `ApprovalMode` 決定是否需要主帳號授權（Auto / SemiAuto / Manual）。

**靈魂回饋迴路：** stress_logs 的歷史資料由 `soul/loader.py` 讀取，注入 SOUL.md 的動態區段，讓 LLM 擁有「自我歷史感」（例如：「上週五我過載了三次」）。

---

## 3. 資料庫 Schema（規範版）

```sql
-- 家庭成員（動態 FAMILY 資料主表）
CREATE TABLE family_members (
    line_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,      -- admin/member/child
    preferences  JSONB DEFAULT '{}',
    access_level INT DEFAULT 1,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 對話歷史
CREATE TABLE conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT REFERENCES family_members(line_id),
    platform   TEXT NOT NULL,        -- line/imessage
    messages   JSONB[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 長期語意記憶（pgvector）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE memory_embeddings (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id   TEXT NOT NULL,
    content   TEXT NOT NULL,
    embedding vector(1536),
    metadata  JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON memory_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- Message Queue（SKIP LOCKED）
CREATE TABLE message_queue (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload      JSONB NOT NULL,
    priority     INT DEFAULT 5,
    status       TEXT DEFAULT 'pending', -- pending/processing/done/failed
    stress_level TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    locked_at    TIMESTAMPTZ
);

-- 小腦袋日記
CREATE TABLE stress_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level        TEXT NOT NULL,
    metrics      JSONB NOT NULL,
    action_taken TEXT,
    mood         TEXT,               -- 供 SOUL.md 動態注入用
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 家庭環境與設備狀態
CREATE TABLE home_context (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    active     BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. 專案目錄結構

```
omni-agent/
├── compose.yml                   # Podman-compatible
├── .env.example
├── SOUL.md                       # 人格核心（git 管理，Markdown）
├── CLAUDE.md                     # 本文件
│
├── gateway/                      # The Senses (Go)
│   ├── Dockerfile
│   ├── cmd/server/main.go
│   └── internal/
│       ├── handler/
│       │   ├── line.go
│       │   └── bluebubbles.go
│       ├── model/
│       │   └── standard_message.go
│       ├── stress/
│       │   └── manager.go        # 小腦袋機制
│       └── forwarder/
│           └── brain.go
│
├── brain/                        # The Brain (Python)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── agent/
│   │   ├── graph.py              # LangGraph state machine
│   │   └── prompts/
│   │       ├── system.py
│   │       └── tools.py
│   ├── llm/                      # ModelRouter + 原廠 SDK
│   │   ├── __init__.py
│   │   ├── base.py               # ModelClient ABC
│   │   ├── claude_client.py      # anthropic SDK + prompt caching
│   │   ├── gemini_client.py      # google-genai SDK + context caching
│   │   ├── local_client.py       # openai SDK → Mac Mini MLX
│   │   └── router.py             # 路由決策 + 模型升級策略
│   ├── memory/
│   │   ├── short_term.py         # conversations table
│   │   └── long_term.py          # pgvector RAG
│   ├── skills/                   # MCP Tools
│   │   ├── proxmox.py
│   │   ├── wake_on_lan.py
│   │   └── home_assistant.py
│   └── soul/
│       ├── loader.py             # SOUL.md + DB → Markdown prompt
│       └── templates/
│           └── context.md.jinja
│
└── docs/
    ├── architecture.md
    └── SECURITY.md
```

---

## 5. 開發階段（Phases）

| Phase | 目標 | 關鍵產出 |
|---|---|---|
| **1** ✅ | Go Gateway + Queue | `StandardMessage{}`, Webhook 驗證, `StressManager` 骨架, PG Queue |
| **2** ✅ | Python Brain + 原廠 SDK | FastAPI 端點, `ModelClient` ABC + Claude/Gemini/Local adapter, prompt/context caching, `ModelRouter` |
| **3** | 記憶系統 + SoulLoader | conversations table, pgvector RAG, `SoulLoader` 讀 SOUL.md, `StressManager` 寫日記 |
| **4** | MCP Skills + 模型升級 | Function Calling, Proxmox/WoL 工具, `ModelRouter` 完整 escalation 實作 |

---

## 6. 開發準則

- **漸進式開發：** 每次只實作一個 Phase，不超前。
- **容器化優先：** 每個服務提供對應 `Dockerfile`，整體提供 `compose.yml`。
- **錯誤處理：** 所有 HTTP / DB 操作必須有 retry 機制與結構化 logging。
- **Shell 指令：** 預設使用 `vi`，不使用 nano。
- **禁止提前優化：** HomeLab 規模，不需要為百萬用量設計。
- **Schema 優先：** 每個 Phase 開始前先確認 DB schema，再寫應用層程式碼。
