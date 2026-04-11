package forwarder

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/jackc/pgx/v5/pgxpool"
)

type BrainResponse struct {
	ReplyText string `json:"reply_text"`
	ModelUsed string `json:"model_used"`
	Provider  string `json:"provider"`
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
			}
		}
	}()
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

	log.Printf("Found message %s, sending to %s", msgId)

	// Set to processing
	_, err = tx.Exec(ctx, "UPDATE message_queue SET status = 'processing', locked_at = NOW() WHERE id = $1", msgId)
	if err != nil {
		return true
	}

	resp, err := http.Post(brainURL, "application/json", bytes.NewReader(payload))
	if err != nil {
		log.Printf("Error sending message %s to brain: %v", msgId, err)
		_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'failed' WHERE id = $1", msgId)
		tx.Commit(ctx)
		return true
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Brain returned non-200 status for message %s: %d", msgId, resp.StatusCode)
		_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'failed' WHERE id = $1", msgId)
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

	// Delivering reply
	var origMsg model.StandardMessage
	_ = json.Unmarshal(payload, &origMsg)

	if brainResp.ReplyText != "" {
		log.Printf("Delivering reply to %s user %s via messenger", origMsg.Platform, origMsg.UserID)
		err = messenger.SendReply(db, origMsg.Platform, origMsg.UserID, brainResp.ReplyText)
		if err != nil {
			log.Printf("Failed to deliver reply for message %s: %v", msgId, err)
			// We might want to keep it as processing or mark as failed, 
			// but for now let's just log it.
		}
	} else {
		log.Printf("Brain returned empty reply for message %s", msgId)
	}
	
	log.Printf("Successfully processed message %s by brain", msgId)
	_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'done' WHERE id = $1", msgId)
	tx.Commit(ctx)
	return true
}
