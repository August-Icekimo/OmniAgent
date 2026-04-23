package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type telegramUpdate struct {
	UpdateID int `json:"update_id"`
	Message  *struct {
		MessageID int `json:"message_id"`
		From      struct {
			ID int64 `json:"id"`
		} `json:"from"`
		Chat struct {
			ID int64 `json:"id"`
		} `json:"chat"`
		Text  string `json:"text"`
		Photo []struct {
			FileID       string `json:"file_id"`
			FileUniqueID string `json:"file_unique_id"`
			FileSize     int64  `json:"file_size"`
		} `json:"photo"`
		Document *struct {
			FileID   string `json:"file_id"`
			FileName string `json:"file_name"`
			MimeType string `json:"mime_type"`
			FileSize int64  `json:"file_size"`
		} `json:"document"`
		Caption string `json:"caption"`
	} `json:"message"`
}


func TelegramWebhook(db *pgxpool.Pool) gin.HandlerFunc {
	webhookSecret := os.Getenv("TELEGRAM_WEBHOOK_SECRET")
	strangerReply := os.Getenv("TELEGRAM_STRANGER_REPLY")
	if strangerReply == "" {
		strangerReply = "Hello! I am a private home AI assistant. I don't recognize you, so I can't process your request."
	}

	return func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "read body error"})
			return
		}

		secretToken := c.GetHeader("X-Telegram-Bot-Api-Secret-Token")
		if secretToken == "" || secretToken != webhookSecret {
			log.Printf("Unauthorized Telegram webhook request, token mismatch. Received: [%s], Expected: [%s]", secretToken, webhookSecret)
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
			return
		}

		var payload telegramUpdate
		if err := json.Unmarshal(body, &payload); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid json"})
			return
		}

		// Only handle message events
		if payload.Message == nil {
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		chatIDStr := strconv.FormatInt(payload.Message.Chat.ID, 10)

		// 1. Identity Lookup
		var userID uuid.UUID
		var role string
		err = db.QueryRow(c.Request.Context(),
			"SELECT u.id, u.role FROM users u JOIN telegram_accounts ta ON u.id = ta.user_id WHERE ta.chat_id = $1",
			chatIDStr).Scan(&userID, &role)

		if err != nil || role == "stranger" {
			// Stranger handling
			log.Printf("Stranger/Unauthorized chat_id: %s", chatIDStr)

			// Log to stranger_knocks
			msgExcerpt := payload.Message.Text
			if len(msgExcerpt) > 100 {
				msgExcerpt = msgExcerpt[:100] + "..."
			}
			_, _ = db.Exec(c.Request.Context(),
				"INSERT INTO stranger_knocks (platform, external_id, first_message) VALUES ($1, $2, $3)",
				"telegram", chatIDStr, msgExcerpt)

			messenger.SendReply(db, "telegram", chatIDStr, strangerReply)
			c.JSON(http.StatusOK, gin.H{"status": "stranger_handled"})
			return
		}

		// 2. Message Parsing
		messageType := ""
		text := ""
		var attachment *model.Attachment

		if payload.Message.Text != "" {
			messageType = "text"
			text = payload.Message.Text
		} else if payload.Message.Document != nil {
			messageType = "file"
			text = payload.Message.Caption
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Document.FileID, payload.Message.Document.FileName, payload.Message.Document.MimeType, payload.Message.Document.FileSize)
			if err != nil {
				log.Printf("File download failed: %v", err)
				messenger.SendReply(db, "telegram", chatIDStr, "檔案下載失敗："+err.Error())
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
		} else if len(payload.Message.Photo) > 0 {
			messageType = "image"
			text = payload.Message.Caption
			// Pick the largest photo
			photo := payload.Message.Photo[len(payload.Message.Photo)-1]
			fileName := fmt.Sprintf("photo_%s.jpg", photo.FileUniqueID)
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), photo.FileID, fileName, "image/jpeg", photo.FileSize)
			if err != nil {
				log.Printf("Photo download failed: %v", err)
				messenger.SendReply(db, "telegram", chatIDStr, "圖片下載失敗："+err.Error())
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
		} else {
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		// 3. Queue Message
		msgId := uuid.New().String()
		stdMsg := model.StandardMessage{
			ID:          msgId,
			Platform:    "telegram",
			UserID:      userID.String(),
			MessageType: messageType,
			Text:        text,
			Attachment:  attachment,
		}

		payloadJSON, _ := json.Marshal(stdMsg)

		_, err = db.Exec(c.Request.Context(),
			"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
			msgId, payloadJSON, 5, "pending")
		if err != nil {
			log.Printf("DB write error for telegram updates: %v", err)
			c.JSON(http.StatusOK, gin.H{"error": "db error"})
			return
		}

		// 4. Workspace Logging
		if attachment != nil {
			_, err = db.Exec(c.Request.Context(),
				"INSERT INTO file_workspace_log (local_path, user_id) VALUES ($1, $2) ON CONFLICT (local_path) DO UPDATE SET last_accessed_at = NOW()",
				attachment.LocalPath, userID)
			if err != nil {
				log.Printf("Workspace log error: %v", err)
			}
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}

func downloadTelegramFile(ctx context.Context, userID, fileID, fileName, mimeType string, fileSize int64) (*model.Attachment, error) {
	// Size limit check (10MB)
	if fileSize > 10*1024*1024 {
		return nil, fmt.Errorf("檔案大小超過 10MB 限制")
	}

	botToken := os.Getenv("TELEGRAM_BOT_TOKEN")
	if botToken == "" {
		return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN not set")
	}

	// 1. Get file path from Telegram
	getFilePathURL := fmt.Sprintf("https://api.telegram.org/bot%s/getFile?file_id=%s", botToken, fileID)
	resp, err := http.Get(getFilePathURL)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var getFileResp struct {
		OK     bool `json:"ok"`
		Result struct {
			FilePath string `json:"file_path"`
			FileSize int64  `json:"file_size"`
		} `json:"result"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&getFileResp); err != nil {
		return nil, err
	}
	if !getFileResp.OK {
		return nil, fmt.Errorf("telegram getFile error")
	}

	// Re-check size if not provided initially
	if fileSize == 0 {
		fileSize = getFileResp.Result.FileSize
	}
	if fileSize > 10*1024*1024 {
		return nil, fmt.Errorf("檔案大小超過 10MB 限制")
	}

	// 2. Download the file
	downloadURL := fmt.Sprintf("https://api.telegram.org/file/bot%s/%s", botToken, getFileResp.Result.FilePath)
	
	// Create context with 4s timeout as per NF-01
	downloadCtx, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(downloadCtx, "GET", downloadURL, nil)
	if err != nil {
		return nil, err
	}

	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download error: %s", resp.Status)
	}

	// 3. Save to workspace
	// Sanitize file name to prevent path traversal
	safeFileName := filepath.Base(fileName)
	timestamp := time.Now().Unix()
	localDir := filepath.Join("/workspace/uploads", userID)
	if err := os.MkdirAll(localDir, 0755); err != nil {
		return nil, err
	}

	localPath := filepath.Join(localDir, fmt.Sprintf("%d_%s", timestamp, safeFileName))
	out, err := os.Create(localPath)
	if err != nil {
		return nil, err
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	if err != nil {
		return nil, err
	}

	return &model.Attachment{
		FileID:    fileID,
		FileName:  fileName,
		MimeType:  mimeType,
		SizeBytes: fileSize,
		LocalPath: localPath,
	}, nil
}
