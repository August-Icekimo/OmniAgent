-- Migration 005: Add oauth_tokens table for Gemini OAuth caching
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT,
    refresh_token TEXT,
    expiry_ms BIGINT,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
