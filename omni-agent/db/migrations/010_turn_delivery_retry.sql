-- Migration 010: turn 投遞失敗的退避重試與 dead-letter (forwarder-delivery-failure-handling)
-- 投遞失敗原本只 log、turn 照標 delivered/done → 答案靜默丟失。
-- 加重試簿記欄位 + next_delivery_at 退避閘門 + undeliverable 終局（保留 result，供 admin 摘要追蹤）。

-- 1. turns：投遞重試簿記
--    delivery_attempts：已嘗試投遞次數（達 5 次仍失敗 → undeliverable）。
--    next_delivery_at：退避閘門（NULL = 立即可投；未來時間 = 等到期才重試，避免緊迴圈與 head-of-line blocking）。
ALTER TABLE turns ADD COLUMN IF NOT EXISTS delivery_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE turns ADD COLUMN IF NOT EXISTS next_delivery_at TIMESTAMPTZ;

-- 2. status 新增終局值 undeliverable（無 CHECK 約束，僅語意註解）：
--    assembling | processing | done | delivered | cancelled | failed | undeliverable
--    undeliverable = 投遞耗盡/終局錯誤，保留 result 供人工檢視與 admin 摘要（dead-letter）。

-- 3. 投遞掃描索引：done 且 next_delivery_at 到期（或從未排程）才取。
--    取代 009 的 turns_deliverable（原僅 WHERE status='done'），納入退避閘門。
DROP INDEX IF EXISTS turns_deliverable;
CREATE INDEX IF NOT EXISTS turns_deliverable
    ON turns (next_delivery_at NULLS FIRST, updated_at)
    WHERE status = 'done';

-- 4. undeliverable dead-letter 掃描（admin 摘要查未報項用）。
CREATE INDEX IF NOT EXISTS turns_undeliverable
    ON turns (updated_at)
    WHERE status = 'undeliverable';
