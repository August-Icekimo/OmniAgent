package handler

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/google/uuid"
	"omni-agent/gateway/internal/model"
	"omni-agent/gateway/internal/queue"
)

type LineHandler struct {
	secret string
	repo   *queue.Repository
}

func NewLineHandler(repo *queue.Repository) *LineHandler {
	secret := os.Getenv("LINE_CHANNEL_SECRET")
	if secret == "" {
		slog.Error("missing necessary LINE_CHANNEL_SECRET for webhook")
		os.Exit(1)
	}

	return &LineHandler{
		secret: secret,
		repo:   repo,
	}
}

// Structs reflecting the LINE webhook payload roughly
type LineWebhookPayload struct {
	Events []LineEvent `json:"events"`
}

type LineEvent struct {
	Type       string          `json:"type"`
	ReplyToken string          `json:"replyToken"`
	Source     LineSource      `json:"source"`
	Message    LineMessage     `json:"message"`
	RawEvent   json.RawMessage `json:"-"`
}

type LineSource struct {
	Type   string `json:"type"`
	UserID string `json:"userId"`
}

type LineMessage struct {
	Type string `json:"type"`
	ID   string `json:"id"`
	Text string `json:"text"`
}

func (h *LineHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("Failed to read body", "error", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	signature := r.Header.Get("X-Line-Signature")
	if signature == "" || !h.validateSignature(body, signature) {
		slog.Warn("Invalid LINE signature")
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	var payload LineWebhookPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		slog.Error("Failed to parse LINE body", "error", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}

	// We can immediately reply 200 OK since actual processing is async or fast enough
	w.WriteHeader(http.StatusOK)

	// Since we reply 200, we'll write to queue asynchronously or at least not block the HTTP client if it's slow over network
	// For now, doing it synchronously here is fast enough for postgres, but we could wrap it in a goroutine
	go h.processEvents(payload)
}

func (h *LineHandler) processEvents(payload LineWebhookPayload) {
	for _, event := range payload.Events {
		if event.Type != "message" {
			// Silently ignore non-message events per requirements
			slog.Debug("Ignoring non-message event", "type", event.Type)
			continue
		}

		msgType := "other"
		if event.Message.Type == "text" {
			msgType = "text"
		} else if event.Message.Type == "image" {
			msgType = "image"
		} else if event.Message.Type == "sticker" {
			msgType = "sticker"
		}

		rawBytes, _ := json.Marshal(event)

		stdMsg := model.StandardMessage{
			ID:          uuid.New(),
			Platform:    "line",
			UserID:      event.Source.UserID,
			DisplayName: "", // Optional, fetched elsewhere or we don't have it directly in typical event
			Text:        event.Message.Text,
			MessageType: msgType,
			RawPayload:  rawBytes,
			ReceivedAt:  time.Now(),
		}

		// Logging event without sensitive payload
		slog.Info("LINE message received", "platform", "line", "user_id", event.Source.UserID)

		// Priority is 5 by default
		if err := h.repo.Enqueue(context.Background(), &stdMsg, 5); err != nil {
			slog.Error("Failed to enqueue LINE message", "error", err)
		}
	}
}

func (h *LineHandler) validateSignature(body []byte, signature string) bool {
	hash := hmac.New(sha256.New, []byte(h.secret))
	hash.Write(body)
	expectedMAC := base64.StdEncoding.EncodeToString(hash.Sum(nil))
	return hmac.Equal([]byte(expectedMAC), []byte(signature))
}
