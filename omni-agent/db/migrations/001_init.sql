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
