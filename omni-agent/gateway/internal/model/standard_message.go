package model

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// StandardMessage represents a unified message from any platform.
type StandardMessage struct {
	ID          uuid.UUID       `json:"id"`
	Platform    string          `json:"platform"`     // "line" or "imessage"
	UserID      string          `json:"user_id"`      // sender's ID (e.g., line user ID, or handle)
	DisplayName string          `json:"display_name"` // optional
	Text        string          `json:"text"`         // text content
	MessageType string          `json:"message_type"` // "text", "image", "sticker", "other"
	RawPayload  json.RawMessage `json:"raw_payload"`  // Original provider's payload
	ReceivedAt  time.Time       `json:"received_at"`
}
