package forwarder

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/jackc/pgx/v5/pgxpool"
)

type BrainResponse struct {
	ReplyText     string `json:"reply_text"`
	ModelUsed     string `json:"model_used"`
	Provider      string `json:"provider"`
	ContextTokens int    `json:"context_tokens"`
	ContextLength int    `json:"context_length"`
}

func StartBrainForwarder(db *pgxpool.Pool) {
	brainURL := os.Getenv("BRAIN_URL")
	if brainURL == "" {
		log.Println("BRAIN_URL is not set")
		return
	}

	log.Printf("Starting Brain Forwarder with URL: %s", brainURL)
	ticker := time.NewTicker(1 * time.Second)
	go func() {
		log.Printf("Brain Forwarder loop started.")
		lastActivity := time.Now()
		for range ticker.C {
			found := processNextMessage(db, brainURL)
			if found {
				lastActivity = time.Now()
			} else if time.Since(lastActivity) >= 1*time.Minute {
				log.Printf("Checking for next message to process (heartbeat)...")
				lastActivity = time.Now()
				cleanupPendingReplies(db)
			}
		}
	}()
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

// buildFooter 組裝 runtime footer（FOOTER_ENABLED=true 才啟用）。
// 欄位資料缺失時靜默跳過，兩欄皆空回傳空字串。
func buildFooter(resp *BrainResponse) string {
	if os.Getenv("FOOTER_ENABLED") != "true" {
		return ""
	}
	var parts []string
	if resp.ModelUsed != "" && resp.ModelUsed != "unknown" {
		// 去掉 vendor 前綴（"openai/gpt-x" → "gpt-x"），目前 model 名多半無前綴
		model := resp.ModelUsed
		if idx := strings.LastIndex(model, "/"); idx >= 0 {
			model = model[idx+1:]
		}
		parts = append(parts, model)
	}
	if resp.ContextLength > 0 && resp.ContextTokens >= 0 {
		pct := resp.ContextTokens * 100 / resp.ContextLength
		if pct > 100 {
			pct = 100
		}
		parts = append(parts, fmt.Sprintf("%d%%", pct))
	}
	if len(parts) == 0 {
		return ""
	}
	return "\n\n— " + strings.Join(parts, " · ")
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

func processNextMessage(db *pgxpool.Pool, brainURL string) bool {
	ctx := context.Background()
	tx, err := db.Begin(ctx)
	if err != nil {
		return false
	}
	defer tx.Rollback(ctx)

	var msgId string
	var payload []byte
	err = tx.QueryRow(ctx, `
		SELECT id, payload
		FROM message_queue
		WHERE status = 'pending'
		ORDER BY priority DESC, created_at ASC
		FOR UPDATE SKIP LOCKED
		LIMIT 1
	`).Scan(&msgId, &payload)

	if err != nil {
		// no rows or message check failed
		return false
	}

	log.Printf("Found message %s, sending to %s", msgId, brainURL)

	var origMsg model.StandardMessage
	_ = json.Unmarshal(payload, &origMsg)

	// Set to processing
	_, err = tx.Exec(ctx, "UPDATE message_queue SET status = 'processing', locked_at = NOW() WHERE id = $1", msgId)
	if err != nil {
		return true
	}

	resp, err := http.Post(brainURL, "application/json", bytes.NewReader(payload))
	if err != nil {
		log.Printf("Error sending message %s to brain: %v", msgId, err)
		_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'failed' WHERE id = $1", msgId)
		failPendingLineReply(db, ctx, &origMsg)
		tx.Commit(ctx)
		return true
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Brain returned non-200 status for message %s: %d", msgId, resp.StatusCode)
		_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'failed' WHERE id = $1", msgId)
		failPendingLineReply(db, ctx, &origMsg)
		tx.Commit(ctx)
		return true
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("Error reading brain response for %s: %v", msgId, err)
		return true
	}

	var brainResp BrainResponse
	if err := json.Unmarshal(body, &brainResp); err != nil {
		log.Printf("Error parsing brain response for %s: %v", msgId, err)
		return true
	}

	if brainResp.ReplyText != "" {
		replyText := brainResp.ReplyText + buildFooter(&brainResp)

		// 慢回應按鈕已送出的情況：答案進快取，改由使用者點 postback 取件
		if claimPendingLineReply(db, ctx, &origMsg, replyText) {
			log.Printf("Reply for message %s cached for postback delivery", msgId)
		} else {
			log.Printf("Delivering reply to %s user %s via messenger", origMsg.Platform, origMsg.UserID)
			opts := &messenger.SendOptions{
				ReplyToken:          origMsg.ReplyToken,
				ReplyTokenExpiresAt: origMsg.ReplyTokenExpiresAt,
				QuoteToken:          origMsg.QuoteToken,
			}
			if origMsg.Platform == "telegram" {
				opts.ReplyToMessageID = origMsg.SourceMessageID
			}
			err = messenger.SendReplyWithOptions(db, origMsg.Platform, origMsg.UserID, replyText, opts)
			if err != nil {
				log.Printf("Failed to deliver reply for message %s: %v", msgId, err)
				// We might want to keep it as processing or mark as failed,
				// but for now let's just log it.
			}
		}
	} else {
		log.Printf("Brain returned empty reply for message %s", msgId)
	}

	log.Printf("Successfully processed message %s by brain", msgId)
	_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'done' WHERE id = $1", msgId)
	tx.Commit(ctx)
	return true
}
