package model

type Attachment struct {
	FileID     string `json:"file_id"`
	FileName   string `json:"file_name"`
	MimeType   string `json:"mime_type"`
	SizeBytes  int64  `json:"size_bytes"`
	LocalPath  string `json:"local_path"`
	MediaType  string `json:"media_type,omitempty"` // image, voice, sticker, animation
	DurationMs int    `json:"duration_ms,omitempty"`
}

type StandardMessage struct {
	ID              string      `json:"id"`
	SourceMessageID string      `json:"source_message_id,omitempty"`
	Platform        string      `json:"platform"`
	UserID          string      `json:"user_id"`
	MessageType     string      `json:"message_type"` // text, image, voice, sticker, animation, file
	Text            string      `json:"text,omitempty"`
	Attachment      *Attachment `json:"attachment,omitempty"`
}
