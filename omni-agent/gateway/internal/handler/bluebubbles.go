package handler

import (
	"context"
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

type BlueBubblesHandler struct {
	password string
	repo     *queue.Repository
}

func NewBlueBubblesHandler(repo *queue.Repository) *BlueBubblesHandler {
	// Not enforcing BLUEBUBBLES_PASSWORD failure on boot, just return 503 from handler if missing
	password := os.Getenv("BLUEBUBBLES_PASSWORD")
	return &BlueBubblesHandler{
		password: password,
		repo:     repo,
	}
}

// Approximate BlueBubbles event struct
type BlueBubblesPayload struct {
	Type string                 `json:"type"`
	Data map[string]interface{} `json:"data"`
}

func (h *BlueBubblesHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if h.password == "" {
		slog.Error("BLUEBUBBLES_PASSWORD not configured")
		http.Error(w, "Service Unavailable", http.StatusServiceUnavailable)
		return
	}

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	passQuery := r.URL.Query().Get("password")
	if passQuery != h.password {
		slog.Warn("Invalid BlueBubbles password")
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		slog.Error("Failed to read body", "error", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	var payload BlueBubblesPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		slog.Error("Failed to parse BlueBubbles body", "error", err)
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}

	// Immediate 200 per standard webhook procedure
	w.WriteHeader(http.StatusOK)

	go h.processEvent(payload, body)
}

func (h *BlueBubblesHandler) processEvent(payload BlueBubblesPayload, rawBody []byte) {
	if payload.Type != "new-message" {
		slog.Debug("Ignoring non-message BlueBubbles event", "type", payload.Type)
		return
	}

	// Try extracting standard fields
	var userID, text string
	msgType := "other"

	// Simplified heuristic extraction of Imessage info; in a real app would strictly decode the nested structs
	if chats, ok := payload.Data["chats"].([]interface{}); ok && len(chats) > 0 {
		if c, ok2 := chats[0].(map[string]interface{}); ok2 {
			if address, ok3 := c["chatIdentifier"].(string); ok3 {
				userID = address
			}
		}
	}
	if msgText, ok := payload.Data["text"].(string); ok {
		text = msgText
		msgType = "text"
	}

	// Fallback ID if couldn't parse properly
	if userID == "" {
		userID = "unknown"
	}

	stdMsg := model.StandardMessage{
		ID:          uuid.New(),
		Platform:    "imessage",
		UserID:      userID,
		Text:        text,
		MessageType: msgType,
		RawPayload:  rawBody,
		ReceivedAt:  time.Now(),
	}

	slog.Info("BlueBubbles message received", "platform", "imessage", "user_id", userID)

	if err := h.repo.Enqueue(context.Background(), &stdMsg, 5); err != nil {
		slog.Error("Failed to enqueue BlueBubbles message", "error", err)
	}
}
