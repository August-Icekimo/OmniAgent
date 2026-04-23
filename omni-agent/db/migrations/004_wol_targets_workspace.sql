-- Phase 4B: WoL Targets and Workspace Management
-- Created At: 2026-04-23

-- Table for WoL targets
CREATE TABLE IF NOT EXISTS wol_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mac TEXT UNIQUE NOT NULL,
    ai_name TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for ai_name lookup
CREATE INDEX IF NOT EXISTS idx_wol_targets_ai_name ON wol_targets(ai_name);

-- Table for tracking workspace files
CREATE TABLE IF NOT EXISTS file_workspace_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    local_path TEXT UNIQUE NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for cleanup query
CREATE INDEX IF NOT EXISTS idx_file_workspace_log_last_accessed ON file_workspace_log(last_accessed_at);
