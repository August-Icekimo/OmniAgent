#!/usr/bin/env bash
# init-omni-agent.sh
# 建立 Omni-Agent 專案目錄結構（Phase 2 架構：三層，無 LiteLLM）
# 使用方式：bash init-omni-agent.sh [目標目錄，預設為 ./omni-agent]

set -euo pipefail

TARGET="${1:-./omni-agent}"

echo "🤖 建立 Omni-Agent 專案結構於：$TARGET"

# ── 根目錄 ────────────────────────────────────────────
mkdir -p "$TARGET"

# --- compose.yml ---
cat > "$TARGET/compose.yml" << 'EOF'
services:
  postgres:
    image: docker.io/pgvector/pgvector:pg18-trixie
    container_name: omni-agent-postgres-1
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-omni}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: ${POSTGRES_DB:-omni_agent}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - ./memory/postgres:/var/lib/postgresql/data
      - ./db/migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-omni} -d ${POSTGRES_DB:-omni_agent}"]
      interval: 3s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  gateway:
    build:
      context: ./gateway
    container_name: omni-agent-gateway-1
    env_file:
      - .env
    ports:
      - "${GATEWAY_PORT:-8080}:8080"
    depends_on:
      postgres:
        condition: service_started
    restart: unless-stopped

  brain:
    build:
      context: ./brain
    container_name: omni-agent-brain-1
    env_file:
      - .env
    ports:
      - "${BRAIN_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_started
    restart: unless-stopped
EOF

touch "$TARGET/.env.example"
touch "$TARGET/.gitignore"

# 複製已生成的靈魂文件（若在同目錄下）
for f in SOUL.md CLAUDE.md; do
  if [ -f "./$f" ]; then
    cp "./$f" "$TARGET/$f"
    echo "  ✅ 複製 $f"
  else
    touch "$TARGET/$f"
    echo "  ⚠️  $f 不存在，建立空白檔案，請手動填入"
  fi
done

# ── Gateway（Go）─────────────────────────────────────
mkdir -p "$TARGET/gateway/cmd/server"
mkdir -p "$TARGET/gateway/internal/handler"
mkdir -p "$TARGET/gateway/internal/model"
mkdir -p "$TARGET/gateway/internal/stress"
mkdir -p "$TARGET/gateway/internal/queue"
mkdir -p "$TARGET/gateway/internal/forwarder"

# --- gateway/Dockerfile ---
cat > "$TARGET/gateway/Dockerfile" << 'EOF'
FROM docker.io/library/golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod ./
# RUN go mod download
COPY . .
RUN go build -o gateway ./cmd/server/main.go

FROM docker.io/library/alpine:latest
WORKDIR /app
COPY --from=builder /app/gateway .
EXPOSE 8080
ENTRYPOINT ["./gateway"]
EOF

touch "$TARGET/gateway/go.mod"
touch "$TARGET/gateway/cmd/server/main.go"
touch "$TARGET/gateway/internal/handler/line.go"
touch "$TARGET/gateway/internal/handler/bluebubbles.go"
touch "$TARGET/gateway/internal/model/standard_message.go"
touch "$TARGET/gateway/internal/stress/manager.go"
touch "$TARGET/gateway/internal/queue/queue.go"
touch "$TARGET/gateway/internal/forwarder/brain.go"

# ── Brain（Python）───────────────────────────────────
mkdir -p "$TARGET/brain/agent/prompts"
mkdir -p "$TARGET/brain/llm"
mkdir -p "$TARGET/brain/memory"
mkdir -p "$TARGET/brain/skills"
mkdir -p "$TARGET/brain/soul/templates"

# --- brain/Dockerfile ---
cat > "$TARGET/brain/Dockerfile" << 'EOF'
FROM docker.io/library/python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

# --- brain/requirements.txt ---
cat > "$TARGET/brain/requirements.txt" << 'EOF'
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
anthropic>=0.52.0
google-genai>=1.12.0
openai>=1.78.0
asyncpg>=0.30.0
pgvector>=0.3.0
jinja2>=3.1.6
langgraph>=0.4.0
pydantic>=2.11.0
python-dotenv>=1.1.0
EOF

touch "$TARGET/brain/main.py"

# agent/（Phase 3 LangGraph）
touch "$TARGET/brain/agent/graph.py"
touch "$TARGET/brain/agent/prompts/system.py"
touch "$TARGET/brain/agent/prompts/tools.py"

# llm/（Phase 2 ModelRouter + 原廠 SDK）
touch "$TARGET/brain/llm/__init__.py"
touch "$TARGET/brain/llm/base.py"
touch "$TARGET/brain/llm/claude_client.py"
touch "$TARGET/brain/llm/gemini_client.py"
touch "$TARGET/brain/llm/local_client.py"
touch "$TARGET/brain/llm/router.py"

# memory/（Phase 3）
touch "$TARGET/brain/memory/short_term.py"
touch "$TARGET/brain/memory/long_term.py"

# skills/（Phase 4 MCP）
touch "$TARGET/brain/skills/__init__.py"
touch "$TARGET/brain/skills/proxmox.py"
touch "$TARGET/brain/skills/wake_on_lan.py"
touch "$TARGET/brain/skills/home_assistant.py"

# soul/（Phase 3 SoulLoader）
touch "$TARGET/brain/soul/loader.py"
touch "$TARGET/brain/soul/templates/context.md.jinja"

# ── Memory（PostgreSQL volumes）──────────────────────
mkdir -p "$TARGET/memory/postgres"

# ── Groups（per-group context）───────────────────────
mkdir -p "$TARGET/groups/family"
mkdir -p "$TARGET/groups/homelab"

touch "$TARGET/groups/family/CLAUDE.md"
touch "$TARGET/groups/homelab/CLAUDE.md"

# ── Docs ─────────────────────────────────────────────
mkdir -p "$TARGET/docs"

touch "$TARGET/docs/architecture.md"
touch "$TARGET/docs/SECURITY.md"

# ── DB migrations ────────────────────────────────────
mkdir -p "$TARGET/db/migrations"

# ── .gitignore 預設內容 ───────────────────────────────
cat > "$TARGET/.gitignore" << 'EOF'
.env
memory/postgres/
*.db
__pycache__/
*.pyc
.DS_Store
EOF

# ── .env.example 預設內容 ─────────────────────────────
cat > "$TARGET/.env.example" << 'EOF'
# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=omni_agent
POSTGRES_USER=omni
POSTGRES_PASSWORD=changeme

# LINE
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=

# BlueBubbles
BLUEBUBBLES_SERVER_URL=
BLUEBUBBLES_PASSWORD=

# LLM — 原廠 SDK 直連（填入即啟用對應 provider）
ANTHROPIC_API_KEY=          # Claude (預設 provider)
GEMINI_API_KEY=             # Gemini (可選，fallback)
MLX_BASE_URL=               # Local MLX, e.g. http://mac-mini.local:8080/v1
MLX_MODEL=mlx-community/Meta-Llama-3.1-8B-Instruct-4bit

# Brain
BRAIN_URL=http://brain:8000/chat
BRAIN_PORT=8000

# Gateway
GATEWAY_PORT=8080
EOF

# ── db/migrations/001_init.sql ────────────────────────
cat > "$TARGET/db/migrations/001_init.sql" << 'EOF'
-- Omni-Agent — Initial Schema
-- Phase 1+2 骨架，後續 Phase 逐步填充
-- 注意：使用 gen_random_uuid()（PostgreSQL 13+ 內建，不需 uuid-ossp extension）

CREATE EXTENSION IF NOT EXISTS vector;

-- 家庭成員（動態 FAMILY 資料主表）
CREATE TABLE IF NOT EXISTS family_members (
    line_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member', -- admin/member/child
    preferences  JSONB DEFAULT '{}',
    access_level INT DEFAULT 1,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 對話歷史（Phase 3 Brain 記憶使用）
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT REFERENCES family_members(line_id),
    platform   TEXT NOT NULL,                    -- line/imessage
    messages   JSONB[] DEFAULT '{}',             -- 每筆為 {role, content}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 長期語意記憶（pgvector RAG — Phase 3）
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    TEXT NOT NULL,
    content    TEXT NOT NULL,
    embedding  vector(1536),
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS memory_embeddings_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

-- Message Queue（SKIP LOCKED — Phase 1 Gateway 核心）
CREATE TABLE IF NOT EXISTS message_queue (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload      JSONB NOT NULL,
    priority     INT DEFAULT 5,
    status       TEXT DEFAULT 'pending',         -- pending/processing/done/failed
    stress_level TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    locked_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS message_queue_pending
    ON message_queue (priority DESC, created_at ASC)
    WHERE status = 'pending';

-- 小腦袋日記（StressManager — 供 soul/loader.py 動態注入 SOUL.md）
CREATE TABLE IF NOT EXISTS stress_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level        TEXT NOT NULL,                  -- StressCalm/Busy/Overload/Critical
    metrics      JSONB NOT NULL,
    action_taken TEXT,
    mood         TEXT,                           -- 中文心情短語，供 LLM 自我歷史感
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 家庭環境與設備狀態（JSONB kv store）
CREATE TABLE IF NOT EXISTS home_context (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    active     BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
EOF

# ── 完成 ──────────────────────────────────────────────
echo ""
echo "✅ 專案結構建立完成！"
echo ""
echo "📁 目錄總覽："
find "$TARGET" -not -path "*/.git/*" -not -path "*/memory/postgres/*" | sort | \
  awk '{
    n = split($0, a, "/");
    printf "%s%s\n", substr("                              ", 1, (n-2)*2), a[n]
  }'

echo ""
echo "📋 下一步："
echo "  1. cd $TARGET"
echo "  2. cp .env.example .env && vi .env          # 填入 ANTHROPIC_API_KEY 等"
echo "  3. 確認 SOUL.md 與 CLAUDE.md 內容正確"
echo "  4. podman compose up -d --build              # 啟動 postgres + gateway + brain"
echo "  5. curl http://localhost:8080/health         # 確認 gateway"
echo "  6. curl http://localhost:8000/health         # 確認 brain"
