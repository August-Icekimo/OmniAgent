-- Phase 4 Skills & Stranger Knocks
-- For storing unauthorized attempts and skill-related status

BEGIN;

CREATE TABLE IF NOT EXISTS stranger_knocks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform      TEXT NOT NULL,                    -- telegram/line
    external_id   TEXT NOT NULL,                    -- telegram chat_id or line_id
    first_message TEXT,
    notified_at   TIMESTAMPTZ,                      -- When admin was notified
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Index for daily summary performance
CREATE INDEX IF NOT EXISTS stranger_knocks_notified_idx ON stranger_knocks (notified_at) WHERE notified_at IS NULL;

-- Skills storage (optional, for persistent skill settings if needed)
-- Currently we store skill status in home_context with 'skill:' prefix.

COMMIT;
