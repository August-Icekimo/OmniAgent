-- Migration 006: Add voice_transcripts table for Phase 4D
-- Requirement: Persistence of voice transcripts for Phase 5 preference learning.

CREATE TABLE IF NOT EXISTS voice_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_platform TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    audio_path TEXT, -- Can be NULL after 120hr cleanup
    duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for Phase 5 preference learning queries: "most recent N transcripts for user X"
CREATE INDEX IF NOT EXISTS idx_voice_transcripts_user_created ON voice_transcripts (user_id, created_at DESC);
