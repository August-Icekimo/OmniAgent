-- Migration 007: LINE 慢回應 postback 狀態機儲存層 (ideas-from-hermes)
-- LLM 超過門檻未回覆時，gateway 燒掉 reply token 送「取得答案」按鈕；
-- brain 回覆先快取於此，待使用者點按 postback（帶新 reply token）免費投遞。
-- 狀態機：pending → ready → delivered，失敗為 error。

CREATE TABLE IF NOT EXISTS line_pending_replies (
    rid        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id    TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | delivered | error
    payload    TEXT,                             -- ready 時存回覆全文（含 footer）
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- forwarder 以 (line_id, state='pending') 認領、postback 以 rid 取件
CREATE INDEX IF NOT EXISTS idx_lpr_line_id_state ON line_pending_replies (line_id, state);
