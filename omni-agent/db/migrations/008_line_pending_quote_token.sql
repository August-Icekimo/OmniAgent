-- Migration 008: line_pending_replies 補 quote_token
-- 慢回應 postback 取件的答案原本不帶引用框——快取時只存了純文字。
-- 按鈕建立時把原訊息的 quoteToken 一起存，取件投遞時掛上引用。

ALTER TABLE line_pending_replies ADD COLUMN IF NOT EXISTS quote_token TEXT;
