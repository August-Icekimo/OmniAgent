package model

type Attachment struct {
	FileID    string `json:"file_id"`
	FileName  string `json:"file_name"`
	MimeType  string `json:"mime_type"`
	SizeBytes int64  `json:"size_bytes"`
	LocalPath string `json:"local_path"`
}

type StandardMessage struct {
	ID          string      `json:"id"`
	Platform    string      `json:"platform"`
	UserID      string      `json:"user_id"`
	MessageType string      `json:"message_type"`
	Text        string      `json:"text,omitempty"`
	Attachment  *Attachment `json:"attachment,omitempty"`
}
