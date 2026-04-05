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
    embedding  vector(768),
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
