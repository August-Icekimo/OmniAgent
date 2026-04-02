package forwarder

import (
	"bytes"
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func StartBrainForwarder(db *pgxpool.Pool) {
	brainURL := os.Getenv("BRAIN_URL")
	if brainURL == "" {
		log.Println("BRAIN_URL is not set")
		return
	}

	ticker := time.NewTicker(1 * time.Second)
	go func() {
		for range ticker.C {
			processNextMessage(db, brainURL)
		}
	}()
}

func processNextMessage(db *pgxpool.Pool, brainURL string) {
	ctx := context.Background()
	tx, err := db.Begin(ctx)
	if err != nil {
		return
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
		// no rows or error
		return
	}

	// Set to processing
	_, err = tx.Exec(ctx, "UPDATE message_queue SET status = 'processing', locked_at = NOW() WHERE id = $1", msgId)
	if err != nil {
		return
	}

	// We must commit here and do the request outside of the lock,
	// or we hold the DB lock while making HTTP requests (bad practice).
	// Actually, SKIP LOCKED is meant to hold the lock until the transaction finishes.
	// We make it simple for Phase 1: hold the lock.
	
	resp, err := http.Post(brainURL, "application/json", bytes.NewReader(payload))
	if err != nil || resp.StatusCode != http.StatusOK {
		_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'failed' WHERE id = $1", msgId)
		tx.Commit(ctx)
		return
	}
	
	_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'done' WHERE id = $1", msgId)
	tx.Commit(ctx)
}
