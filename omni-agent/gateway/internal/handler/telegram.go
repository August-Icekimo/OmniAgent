package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	tgAckMap  = make(map[string]time.Time)
	tgAckLock sync.Mutex
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
		Voice *struct {
			FileID   string `json:"file_id"`
			Duration int    `json:"duration"`
			MimeType string `json:"mime_type"`
			FileSize int64  `json:"file_size"`
		} `json:"voice"`
		Sticker *struct {
			FileID     string `json:"file_id"`
			IsAnimated bool   `json:"is_animated"`
			IsVideo    bool   `json:"is_video"`
			FileSize   int64  `json:"file_size"`
		} `json:"sticker"`
		Animation *struct {
			FileID   string `json:"file_id"`
			FileName string `json:"file_name"`
			MimeType string `json:"mime_type"`
			FileSize int64  `json:"file_size"`
		} `json:"animation"`
		Video *struct {
			FileID   string `json:"file_id"`
			Duration int    `json:"duration"`
			FileSize int64  `json:"file_size"`
		} `json:"video"`
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
		} else if payload.Message.Voice != nil {
			messageType = "voice"
			text = payload.Message.Caption
			sendMultimodalAck(db, "telegram", chatIDStr, "voice")
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Voice.FileID, "voice.ogg", "audio/ogg", payload.Message.Voice.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			attachment.MediaType = "voice"
			attachment.DurationMs = payload.Message.Voice.Duration * 1000
		} else if len(payload.Message.Photo) > 0 {
			messageType = "image"
			text = payload.Message.Caption
			sendMultimodalAck(db, "telegram", chatIDStr, "image")
			// Pick the largest photo
			photo := payload.Message.Photo[len(payload.Message.Photo)-1]
			fileName := fmt.Sprintf("photo_%s.jpg", photo.FileUniqueID)
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), photo.FileID, fileName, "image/jpeg", photo.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			attachment.MediaType = "image"
		} else if payload.Message.Sticker != nil {
			messageType = "sticker"
			sendMultimodalAck(db, "telegram", chatIDStr, "image")
			fileName := "sticker.webp"
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Sticker.FileID, fileName, "image/webp", payload.Message.Sticker.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			attachment.MediaType = "sticker"
			// Check for TGS (Gzipped JSON)
			if isGzipped(attachment.LocalPath) {
				attachment.MediaType = "tgs_sticker"
			} else if payload.Message.Sticker.IsAnimated || payload.Message.Sticker.IsVideo {
				firstFramePath := attachment.LocalPath + ".jpg"
				if err := extractFirstFrame(attachment.LocalPath, firstFramePath); err == nil {
					attachment.LocalPath = firstFramePath
					attachment.MimeType = "image/jpeg"
				}
			}
		} else if payload.Message.Animation != nil {
			messageType = "animation"
			text = payload.Message.Caption
			sendMultimodalAck(db, "telegram", chatIDStr, "image")
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Animation.FileID, "animation.mp4", "video/mp4", payload.Message.Animation.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			attachment.MediaType = "animation"
			// Extract first frame for GIF/Animation
			firstFramePath := attachment.LocalPath + ".jpg"
			if err := extractFirstFrame(attachment.LocalPath, firstFramePath); err == nil {
				attachment.LocalPath = firstFramePath
				attachment.MimeType = "image/jpeg"
			}
		} else if payload.Message.Video != nil {
			messageType = "video"
			text = payload.Message.Caption
			sendMultimodalAck(db, "telegram", chatIDStr, "image")
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Video.FileID, "video.mp4", "video/mp4", payload.Message.Video.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			attachment.MediaType = "video"
			attachment.DurationMs = payload.Message.Video.Duration * 1000
		} else if payload.Message.Document != nil {
			messageType = "file"
			text = payload.Message.Caption
			attachment, err = downloadTelegramFile(c.Request.Context(), userID.String(), payload.Message.Document.FileID, payload.Message.Document.FileName, payload.Message.Document.MimeType, payload.Message.Document.FileSize)
			if err != nil {
				handleDownloadError(db, chatIDStr, err)
				c.JSON(http.StatusOK, gin.H{"status": "download_failed"})
				return
			}
			// Handle HEIF/HEIC Conversion
			ext := filepath.Ext(attachment.FileName)
			if ext == ".heic" || ext == ".heif" {
				jpgPath := attachment.LocalPath + ".jpg"
				if err := convertHeifToJpg(attachment.LocalPath, jpgPath); err == nil {
					attachment.LocalPath = jpgPath
					attachment.MimeType = "image/jpeg"
					attachment.MediaType = "image"
					messageType = "image"
				}
			}
		} else {
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		// 3. Queue Message
		msgId := uuid.New().String()
		stdMsg := model.StandardMessage{
			ID:              msgId,
			SourceMessageID: strconv.Itoa(payload.Message.MessageID),
			Platform:        "telegram",
			UserID:          userID.String(),
			MessageType:     messageType,
			Text:            text,
			Attachment:      attachment,
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

func sendMultimodalAck(db *pgxpool.Pool, platform, chatID, modality string) {
	tgAckLock.Lock()
	defer tgAckLock.Unlock()

	lastAck, ok := tgAckMap[chatID]
	if ok && time.Since(lastAck) < 5*time.Second {
		return
	}

	var ackText string
	switch modality {
	case "voice":
		ackText = "嗯,收到了,正在聽..."
	case "image", "sticker", "animation":
		ackText = "嗯,收到了,正在看..."
	default:
		ackText = "嗯,收到了,正在看..."
	}

	messenger.SendReply(db, platform, chatID, ackText)
	tgAckMap[chatID] = time.Now()
}

func handleDownloadError(db *pgxpool.Pool, chatID string, err error) {
	log.Printf("Download failed: %v", err)
	errMsg := "下載失敗"
	if err.Error() == "檔案大小超過 10MB 限制" {
		errMsg = "檔案大小超過 10MB 限制，我現在還吞不下這麼大的東西..."
	}
	messenger.SendReply(db, "telegram", chatID, errMsg)
}

func extractFirstFrame(inputPath, outputPath string) error {
	cmd := exec.Command("ffmpeg", "-i", inputPath, "-frames:v", "1", "-update", "1", outputPath, "-y")
	return cmd.Run()
}

func convertHeifToJpg(inputPath, outputPath string) error {
	cmd := exec.Command("vips", "copy", inputPath, outputPath)
	return cmd.Run()
}

func isGzipped(path string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()

	buf := make([]byte, 2)
	_, err = f.Read(buf)
	if err != nil {
		return false
	}
	// Magic bytes for GZIP: 1F 8B
	return buf[0] == 0x1f && buf[1] == 0x8b
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
