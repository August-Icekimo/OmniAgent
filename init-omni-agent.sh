#!/usr/bin/env bash
# init-omni-agent.sh
# 建立 Omni-Agent 專案目錄結構
# 使用方式：bash init-omni-agent.sh [目標目錄，預設為 ./omni-agent]

set -euo pipefail

TARGET="${1:-./omni-agent}"

echo "🤖 建立 Omni-Agent 專案結構於：$TARGET"

# ── 根目錄 ────────────────────────────────────────────
mkdir -p "$TARGET"

touch "$TARGET/compose.yml"
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
mkdir -p "$TARGET/gateway/internal/forwarder"

touch "$TARGET/gateway/Dockerfile"
touch "$TARGET/gateway/go.mod"
touch "$TARGET/gateway/cmd/server/main.go"
touch "$TARGET/gateway/internal/handler/line.go"
touch "$TARGET/gateway/internal/handler/bluebubbles.go"
touch "$TARGET/gateway/internal/model/standard_message.go"
touch "$TARGET/gateway/internal/stress/manager.go"
touch "$TARGET/gateway/internal/forwarder/brain.go"

# ── Brain（Python）───────────────────────────────────
mkdir -p "$TARGET/brain/agent/prompts"
mkdir -p "$TARGET/brain/memory"
mkdir -p "$TARGET/brain/skills"
mkdir -p "$TARGET/brain/soul/templates"

touch "$TARGET/brain/Dockerfile"
touch "$TARGET/brain/requirements.txt"
touch "$TARGET/brain/main.py"
touch "$TARGET/brain/agent/graph.py"
touch "$TARGET/brain/agent/router.py"
touch "$TARGET/brain/agent/prompts/system.py"
touch "$TARGET/brain/agent/prompts/tools.py"
touch "$TARGET/brain/memory/short_term.py"
touch "$TARGET/brain/memory/long_term.py"
touch "$TARGET/brain/skills/__init__.py"
touch "$TARGET/brain/skills/proxmox.py"
touch "$TARGET/brain/skills/wake_on_lan.py"
touch "$TARGET/brain/skills/home_assistant.py"
touch "$TARGET/brain/soul/loader.py"
touch "$TARGET/brain/soul/templates/context.md.jinja"

# ── Router（LiteLLM）─────────────────────────────────
mkdir -p "$TARGET/router"

touch "$TARGET/router/Dockerfile"
touch "$TARGET/router/config.yaml"

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
touch "$TARGET/db/migrations/001_init.sql"

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

# LiteLLM
LITELLM_URL=http://litellm:4000
LITELLM_MASTER_KEY=changeme

# Gemini
GEMINI_API_KEY=

# Brain
BRAIN_URL=http://brain:8000

# Gateway
GATEWAY_PORT=8080
EOF

# ── db/migrations/001_init.sql ────────────────────────
cat > "$TARGET/db/migrations/001_init.sql" << 'EOF'
-- Omni-Agent — Initial Schema
-- Phase 1 骨架，後續 Phase 逐步填充

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- 家庭成員
CREATE TABLE IF NOT EXISTS family_members (
    line_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member', -- admin/member/child
    preferences  JSONB DEFAULT '{}',
    access_level INT DEFAULT 1,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 對話歷史
CREATE TABLE IF NOT EXISTS conversations (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    TEXT REFERENCES family_members(line_id),
    platform   TEXT NOT NULL, -- line/imessage
    messages   JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 長期語意記憶（pgvector）
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    TEXT NOT NULL,
    content    TEXT NOT NULL,
    embedding  vector(1536),
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS memory_embeddings_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

-- Message Queue（SKIP LOCKED）
CREATE TABLE IF NOT EXISTS message_queue (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    payload      JSONB NOT NULL,
    priority     INT DEFAULT 5,
    status       TEXT DEFAULT 'pending', -- pending/processing/done/failed
    stress_level TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    locked_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS message_queue_pending
    ON message_queue (priority DESC, created_at ASC)
    WHERE status = 'pending';

-- 小腦袋日記
CREATE TABLE IF NOT EXISTS stress_logs (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level        TEXT NOT NULL,
    metrics      JSONB NOT NULL,
    action_taken TEXT,
    mood         TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 家庭環境與設備狀態
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
find "$TARGET" -not -path "*/\.*" | sort | \
  awk '{
    n = split($0, a, "/");
    printf "%s%s\n", substr("                              ", 1, (n-2)*2), a[n]
  }'

echo ""
echo "📋 下一步："
echo "  1. cd $TARGET"
echo "  2. cp .env.example .env && vi .env          # 填入你的金鑰"
echo "  3. 確認 SOUL.md 與 CLAUDE.md 內容正確"
echo "  4. 開始 Phase 1：gateway/internal/ 的實作"
