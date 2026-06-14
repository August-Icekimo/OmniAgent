package forwarder

import (
	"context"
	"log"
	"os"
	"strings"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/jackc/pgx/v5/pgxpool"
)

// StartBrainForwarder 啟動 turn 引擎迴圈（單一 goroutine）。每回合：
//  1. assembleTurns  — 把 burst 收斂成 turn（debounce + per-user 序列化）
//  2. dispatchDueTurn — 到期 turn 解耦送 brain /turn（brain 非同步寫回 turns.result）
//  3. deliverDoneTurn — 投遞 brain 已完成的 turn
func StartBrainForwarder(db *pgxpool.Pool) {
	brainURL := os.Getenv("BRAIN_URL")
	if brainURL == "" {
		log.Println("BRAIN_URL is not set")
		return
	}
	turnURL := deriveTurnURL(brainURL)

	log.Printf("Starting Brain Forwarder (turn engine). turn URL: %s", turnURL)
	ticker := time.NewTicker(1 * time.Second)
	go func() {
		log.Printf("Brain Forwarder loop started.")
		lastActivity := time.Now()
		for range ticker.C {
			assembleTurns(db)
			worked := dispatchDueTurn(db, turnURL)
			delivered := deliverDoneTurn(db)
			if worked || delivered {
				lastActivity = time.Now()
			} else if time.Since(lastActivity) >= 1*time.Minute {
				log.Printf("turn engine heartbeat...")
				lastActivity = time.Now()
				cleanupPendingReplies(db)
			}
		}
	}()
}

// deriveTurnURL 由 BRAIN_URL（慣例為 .../chat）推導解耦 turn 端點（.../turn）。
func deriveTurnURL(brainURL string) string {
	if strings.HasSuffix(brainURL, "/chat") {
		return strings.TrimSuffix(brainURL, "/chat") + "/turn"
	}
	return strings.TrimRight(brainURL, "/") + "/turn"
}

// cleanupPendingReplies 比照 hermes 的 TTL：pending 留 24h、其餘留 1h。
func cleanupPendingReplies(db *pgxpool.Pool) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, err := db.Exec(ctx, `
		DELETE FROM line_pending_replies
		WHERE (state = 'pending' AND created_at < NOW() - INTERVAL '24 hours')
		   OR (state <> 'pending' AND updated_at < NOW() - INTERVAL '1 hour')
	`)
	if err != nil {
		log.Printf("line_pending_replies cleanup failed: %v", err)
	}
}

// failPendingLineReply 將該使用者的 pending 列轉為 error，避免按鈕永久等待。
func failPendingLineReply(db *pgxpool.Pool, ctx context.Context, origMsg *model.StandardMessage) {
	if origMsg.Platform != "line" {
		return
	}
	lineID := messenger.ResolveLineID(db, origMsg.UserID)
	_, err := db.Exec(ctx, `
		UPDATE line_pending_replies
		SET state = 'error', updated_at = NOW()
		WHERE line_id = $1 AND state = 'pending'
	`, lineID)
	if err != nil {
		log.Printf("Failed to mark pending reply as error: %v", err)
	}
}

// claimPendingLineReply 認領最早的 pending 列：寫入答案、轉 ready。
// 回傳 true 表示答案改由 postback 取件，不做直接投遞。
func claimPendingLineReply(db *pgxpool.Pool, ctx context.Context, origMsg *model.StandardMessage, replyText string) bool {
	if origMsg.Platform != "line" {
		return false
	}
	lineID := messenger.ResolveLineID(db, origMsg.UserID)
	var rid string
	err := db.QueryRow(ctx, `
		UPDATE line_pending_replies
		SET state = 'ready', payload = $1, updated_at = NOW()
		WHERE rid = (
			SELECT rid FROM line_pending_replies
			WHERE line_id = $2 AND state = 'pending'
			ORDER BY created_at ASC
			LIMIT 1
		)
		RETURNING rid
	`, replyText, lineID).Scan(&rid)
	if err != nil {
		return false // 無 pending 列，正常直接投遞
	}
	log.Printf("LINE: reply cached for postback pickup (rid=%s)", rid)
	return true
}
