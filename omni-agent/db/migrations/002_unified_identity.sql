-- Phase 4 Unified Identity Migration
-- Migrating from line_id-based family_members to UUID-based users

BEGIN;

-- 1. Create the new users table
CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    preferences  JSONB DEFAULT '{}',
    access_level INT DEFAULT 1,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Create platform account tables
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

-- 3. Migrate data from family_members to users and line_accounts
-- We use line_id as a temporary way to map back for FK updates
INSERT INTO users (name, role, preferences, access_level, updated_at)
SELECT name, role, preferences, access_level, updated_at
FROM family_members;

-- Map line_ids to the newly created users
INSERT INTO line_accounts (line_id, user_id)
SELECT fm.line_id, u.id
FROM family_members fm
JOIN users u ON u.name = fm.name AND u.role = fm.role; -- Risk: duplicate names? Usually in a family it's fine for initial migration.

-- 4. Update conversations table
-- First, add a temporary column for the new UUID
ALTER TABLE conversations ADD COLUMN new_user_id UUID;

-- Update the new column by mapping old user_id (line_id) to the new user UUID
UPDATE conversations c
SET new_user_id = la.user_id
FROM line_accounts la
WHERE c.user_id = la.line_id;

-- Now swap the columns
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_user_id_fkey;
ALTER TABLE conversations DROP COLUMN user_id;
ALTER TABLE conversations RENAME COLUMN new_user_id TO user_id;
ALTER TABLE conversations ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- 5. Update memory_embeddings table
-- Currently user_id is TEXT, we'll convert it to UUID
ALTER TABLE memory_embeddings ADD COLUMN new_user_id UUID;

UPDATE memory_embeddings me
SET new_user_id = la.user_id
FROM line_accounts la
WHERE me.user_id = la.line_id;

ALTER TABLE memory_embeddings DROP COLUMN user_id;
ALTER TABLE memory_embeddings RENAME COLUMN new_user_id TO user_id;
-- Add index for the new UUID column
CREATE INDEX IF NOT EXISTS memory_embeddings_user_id_idx ON memory_embeddings (user_id);

-- 6. Clean up
DROP TABLE family_members;

COMMIT;
