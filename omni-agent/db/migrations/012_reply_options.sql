-- Migration 012: 回覆附可點選選項 (reply-quick-options)
-- 確認往返（長影片分析、寫入型工具）的回覆附「好，繼續／取消」按鈕：
-- LINE 投遞為 Quick Reply、Telegram 為 Inline Keyboard；iMessage 不支援，維持純文字。
-- 格式：[{"label": "好，繼續", "text": "好"}, {"label": "取消", "text": "取消"}]
--   label = 按鈕顯示文字；text = 點按後以使用者身分送出的文字。NULL = 無按鈕（既有行為）。

-- 1. turns：brain 寫回覆時一併寫選項，forwarder 投遞時帶出
ALTER TABLE turns ADD COLUMN IF NOT EXISTS options JSONB;

-- 2. line_pending_replies：慢回應改走 postback 取件時，選項跟著快取，取件投遞時一起帶出
ALTER TABLE line_pending_replies ADD COLUMN IF NOT EXISTS options JSONB;
