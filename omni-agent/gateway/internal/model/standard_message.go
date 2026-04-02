package model

type StandardMessage struct {
	ID          string `json:"id"`
	Platform    string `json:"platform"`
	UserID      string `json:"user_id"`
	MessageType string `json:"message_type"`
	Text        string `json:"text,omitempty"`
}
