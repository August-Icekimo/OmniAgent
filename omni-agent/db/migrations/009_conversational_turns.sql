-- Migration 009: 對話回合組裝與原子性 (conversational-turn-assembly)
-- 把同一人的 burst 收斂成一個 turn 再叫 brain；turn 為原子單位直到 commit point。
-- DB 驅動 debounce（gateway 多 worker，in-memory timer 會 race）。
-- per-user 序列化、解耦交付、cancel-on-withdrawal 皆落在 turns 表。

-- 1. message_queue：per-user 分組 + turn 連結
--    user_id 從 payload 反正規化出來，供 per-user 收斂查詢/鎖定（免挖 JSONB）。
ALTER TABLE message_queue ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE message_queue ADD COLUMN IF NOT EXISTS turn_id UUID;

-- 同一人待處理訊息的收斂查詢（debounce 認領用）
CREATE INDEX IF NOT EXISTS message_queue_user_pending
    ON message_queue (user_id, created_at ASC)
    WHERE status = 'pending';

-- 2. turns：組裝後的對話回合（原子單位）
CREATE TABLE IF NOT EXISTS turns (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL,
    platform          TEXT NOT NULL,                    -- line | telegram
    status            TEXT NOT NULL DEFAULT 'assembling',
                      -- assembling | processing | done | delivered | cancelled | failed
                      -- (active = assembling|processing；commit point 是 commit_passed 布林，非狀態)
    silence_deadline  TIMESTAMPTZ NOT NULL,             -- 每來一則訊息 bump（reset-on-each ~4s）
    hard_deadline     TIMESTAMPTZ NOT NULL,             -- 首訊息 + ceiling（~30s）封頂，防餓死
    commit_passed     BOOLEAN NOT NULL DEFAULT false,   -- 原子性：true 後新輸入開新 turn
    cancel_requested  BOOLEAN NOT NULL DEFAULT false,   -- withdrawal/supersede 訊號（brain 輪詢）
    result            TEXT,                             -- 解耦交付：brain 寫回覆全文（含 footer）
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- per-user 序列化：同一人同時只有一個「進行中」turn（assembling 或 processing）
CREATE UNIQUE INDEX IF NOT EXISTS turns_one_active_per_user
    ON turns (user_id)
    WHERE status IN ('assembling', 'processing');

-- forwarder 掃描到期的組裝中 turn（silence 或 hard deadline 到）
CREATE INDEX IF NOT EXISTS turns_due
    ON turns (silence_deadline)
    WHERE status = 'assembling';

-- forwarder 投遞掃描：已完成、待送出的 turn
CREATE INDEX IF NOT EXISTS turns_deliverable
    ON turns (updated_at)
    WHERE status = 'done';
