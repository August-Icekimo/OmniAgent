-- Migration 011: LLM 呼叫用量帳 (llm-usage-accounting)
-- SIWC（ChatGPT Plus）拿不到剩餘額度 → 自記每次 Router.chat 嘗試的 provider／caller／token／延遲，
-- 供觀察期估算各 provider 用量；失敗嘗試也記（token 為 NULL），fallback 次數改由 DB 查，不再依賴容器 log。

CREATE TABLE IF NOT EXISTS llm_usage (
    id                BIGSERIAL PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider          TEXT NOT NULL,
    model             TEXT,
    caller            TEXT NOT NULL,                   -- Router.chat 的 caller（未帶為 unknown）
    ok                BOOLEAN NOT NULL,
    error_type        TEXT,                            -- 失敗時的例外類別名
    fallback          BOOLEAN NOT NULL DEFAULT false,  -- 前一 provider 實際失敗後的嘗試
    latency_ms        INT NOT NULL,
    input_tokens      INT,
    output_tokens     INT,                             -- 計費輸出（含 reasoning／thinking）
    reasoning_tokens  INT,
    cache_read_tokens INT
);

CREATE INDEX IF NOT EXISTS llm_usage_created_at ON llm_usage (created_at);
