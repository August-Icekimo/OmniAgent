package forwarder

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"time"

	"omni-agent/gateway/internal/queue"
)

type BrainForwarder struct {
	repo   *queue.Repository
	url    string
	client *http.Client
}

func NewBrainForwarder(repo *queue.Repository) *BrainForwarder {
	url := os.Getenv("BRAIN_URL")
	if url == "" {
		slog.Warn("BRAIN_URL is not set. Brain Forwarder will not start.")
		return nil
	}

	return &BrainForwarder{
		repo: repo,
		url:  url,
		client: &http.Client{
			// 10s timeout requirement
			Timeout: 10 * time.Second,
		},
	}
}

func (f *BrainForwarder) Start(ctx context.Context) {
	// Simple polling interval (500ms)
	ticker := time.NewTicker(500 * time.Millisecond)

	go func() {
		defer ticker.Stop()
		slog.Info("Brain forwarder started", "url", f.url)

		for {
			select {
			case <-ctx.Done():
				slog.Info("Brain forwarder stopped")
				return
			case <-ticker.C:
				f.poll(ctx)
			}
		}
	}()
}

func (f *BrainForwarder) poll(ctx context.Context) {
	// We run continuously as long as there are messages, otherwise wait for next tick
	for {
		msg, err := f.repo.Dequeue(ctx)
		if err != nil {
			if err == sql.ErrNoRows {
				// Queue empty, wait for next tick
				return
			}
			slog.Error("BrainForwarder: failed to dequeue message", "error", err)
			return
		}

		slog.Debug("Forwarding message to brain...", "msg_id", msg.ID)

		success := f.forward(ctx, msg.Payload)

		if success {
			if err := f.repo.UpdateStatus(ctx, msg.ID, "done"); err != nil {
				slog.Error("Failed to update status to done", "msg_id", msg.ID, "error", err)
			}
		} else {
			if err := f.repo.UpdateStatus(ctx, msg.ID, "failed"); err != nil {
				slog.Error("Failed to update status to failed", "msg_id", msg.ID, "error", err)
			}
		}
	}
}

func (f *BrainForwarder) forward(ctx context.Context, payload interface{}) bool {
	body, err := json.Marshal(payload)
	if err != nil {
		slog.Error("Failed to marshal payload for brain", "error", err)
		return false
	}

	// According to requirement, when brain doesn't respond or responds non 2xx, mark failed
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.url, bytes.NewReader(body))
	if err != nil {
		slog.Error("Failed to create request for brain", "error", err)
		return false
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := f.client.Do(req)
	if err != nil {
		slog.Error("Failed to POST to brain", "error", err)
		return false
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		slog.Error("Brain returned non-2xx status", "status", resp.StatusCode)
		return false
	}

	return true
}
