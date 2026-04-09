#!/usr/bin/env bash
# init-omni-agent.sh
# 建立 Omni-Agent 專案目錄結構 (Phase 4 最終穩定版：LangGraph + MCP Skills + Unified Identity)
# 使用方式：bash init-omni-agent.sh [目標目錄，預設為 ./omni-agent]

set -euo pipefail

TARGET="${1:-./omni-agent}"

echo "🤖 正在初始化 Omni-Agent 專案結構成員：$TARGET"

# ── 根目錄 ────────────────────────────────────────────
mkdir -p "$TARGET"

# --- compose.yml ---
# 包含 Postgres (Vector), Gateway (Go), Brain (Python/LangGraph), Skills (Go/MCP)
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
      - "${GATEWAY_PORT:-8086}:8086"
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
    volumes:
      - ./SOUL.md:/SOUL.md:ro
    depends_on:
      postgres:
        condition: service_started
    restart: unless-stopped

  skills:
    build:
      context: ./skills
    container_name: omni-agent-skills-1
    env_file:
      - .env
    ports:
      - "${SKILLS_PORT:-8001}:8001"
    restart: unless-stopped
EOF

touch "$TARGET/.env.example"
touch "$TARGET/.gitignore"

# 複製已生成的靈魂文件 (若在同目錄下)
for f in SOUL.md CLAUDE.md; do
  if [ -f "./$f" ]; then
    cp "./$f" "$TARGET/$f"
    echo "  ✅ 已複製 $f"
  else
    touch "$TARGET/$f"
    echo "  ⚠️  $f 不存在，已建立空白檔案，請記得填入手感與靈魂"
  fi
done

# ── Gateway (Go API 閘道器) ───────────────────────────
mkdir -p "$TARGET/gateway/cmd/server"
mkdir -p "$TARGET/gateway/internal/handler"
mkdir -p "$TARGET/gateway/internal/model"
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
EXPOSE 8086
ENTRYPOINT ["./gateway"]
EOF

touch "$TARGET/gateway/go.mod"
touch "$TARGET/gateway/cmd/server/main.go"
touch "$TARGET/gateway/internal/handler/line.go"
touch "$TARGET/gateway/internal/handler/telegram.go"
touch "$TARGET/gateway/internal/handler/bluebubbles.go"
touch "$TARGET/gateway/internal/model/standard_message.go"
touch "$TARGET/gateway/internal/queue/queue.go"
touch "$TARGET/gateway/internal/forwarder/brain.go"

# ── Brain (Python LangGraph 大腦) ────────────────────
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
touch "$TARGET/brain/agent/graph.py"
touch "$TARGET/brain/agent/prompts/system.py"
touch "$TARGET/brain/memory/short_term.py"
touch "$TARGET/brain/memory/long_term.py"
touch "$TARGET/brain/soul/loader.py"

# ── Skills (Go MCP 技能服務) ──────────────────────────
mkdir -p "$TARGET/skills/handler"

# --- skills/Dockerfile ---
cat > "$TARGET/skills/Dockerfile" << 'EOF'
FROM docker.io/library/golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY . .
RUN go build -o skills main.go

FROM docker.io/library/alpine:latest
WORKDIR /app
COPY --from=builder /app/skills .
EXPOSE 8001
ENTRYPOINT ["./skills"]
EOF

touch "$TARGET/skills/go.mod"
touch "$TARGET/skills/main.go"
touch "$TARGET/skills/handler/wol.go"
touch "$TARGET/skills/handler/proxmox.go"

# ── 其他支援目錄 ──────────────────────────────────────
mkdir -p "$TARGET/memory/postgres"
mkdir -p "$TARGET/db/migrations"
mkdir -p "$TARGET/docs"

# ── .gitignore ───────────────────────────────────────
cat > "$TARGET/.gitignore" << 'EOF'
.env
memory/postgres/
*.db
__pycache__/
*.pyc
.DS_Store
EOF

# ── .env.example ─────────────────────────────────────
cat > "$TARGET/.env.example" << 'EOF'
# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=omni_agent
POSTGRES_USER=omni
POSTGRES_PASSWORD=changeme

# 平台通訊設定 (填入即啟用)
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_CHAT_IDS=      # 逗號分隔，例如 "12345,67890"

# BlueBubbles (選配)
BLUEBUBBLES_SERVER_URL=
BLUEBUBBLES_PASSWORD=

# LLM 供應商 (優先使用 Anthropic)
ANTHROPIC_API_KEY=
GEMINI_API_KEY=                 # 供 Memory 向量化與備援使用
OPENAI_API_KEY=

# Local LLM (選配)
MLX_BASE_URL=                   # 例如 http://host.docker.internal:8086/v1
MLX_MODEL=

# 系統內部 URL
BRAIN_URL=http://brain:8000/chat
SKILLS_URL=http://skills:8001
GATEWAY_PORT=8086
BRAIN_PORT=8000
SKILLS_PORT=8001
EOF

# ── db/migrations/001_init.sql (Phase 4 整合版) ──────
cat > "$TARGET/db/migrations/001_init.sql" << 'EOF'
-- Omni-Agent 初始化 Schema (Phase 4 穩定版)
CREATE EXTENSION IF NOT EXISTS vector;

-- 核心使用者表 (Unified Identity)
CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member', -- admin/member/child
    preferences  JSONB DEFAULT '{}',
    access_level INT DEFAULT 1,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 通訊平台關聯
CREATE TABLE IF NOT EXISTS line_accounts (
    line_id    TEXT PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_accounts (
    chat_id    TEXT PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 對話歷史 (短期記憶)
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES users(id),
    platform   TEXT NOT NULL,
    messages   JSONB[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 長期語意記憶 (pgvector - 配合 Gemini 768 維度)
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    embedding  vector(768),
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS memory_embeddings_hnsw ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

-- 任務隊列 (Skip Locked)
CREATE TABLE IF NOT EXISTS message_queue (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload      JSONB NOT NULL,
    priority     INT DEFAULT 5,
    status       TEXT DEFAULT 'pending',
    stress_level TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    locked_at    TIMESTAMPTZ
);

-- 系統狀態與壓力日誌 (StressManager)
CREATE TABLE IF NOT EXISTS stress_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level        TEXT NOT NULL,
    metrics      JSONB NOT NULL,
    action_taken TEXT,
    mood         TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 通用 Key-Value 存儲
CREATE TABLE IF NOT EXISTS home_context (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    active     BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 陌生人嘗試觸發記錄 (Stranger Knocks)
CREATE TABLE IF NOT EXISTS stranger_knocks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform      TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    first_message TEXT,
    notified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
EOF

# ── 初始化完成 ─────────────────────────────────────────
echo ""
echo "✅ Omni-Agent Phase 4 專案結構初始化完成！"
echo ""
echo "📋 後續步驟："
echo "  1. cd $TARGET"
echo "  2. cp .env.example .env && vi .env          # 填入金鑰與 Token"
echo "  3. podman compose up -d --build              # 啟動四大核心服務"
echo "  4. 存取 http://localhost:8086/health         # 檢查系統健康狀態"
echo ""
echo "💡 提示：本版本已整合 Unified Identity 與技能系統，請確保 .env 中的 ID 設定正確。"
