package handler

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	lineAckMap  = make(map[string]time.Time)
	lineAckLock sync.Mutex
)

type lineWebhookBody struct {
	Events []struct {
		Type   string `json:"type"`
		Source struct {
			UserId string `json:"userId"`
		} `json:"source"`
		Message struct {
			Type      string `json:"type"`
			Text      string `json:"text"`
			Id        string `json:"id"`
			PackageId string `json:"packageId"`
			StickerId string `json:"stickerId"`
			Duration  int    `json:"duration"`
		} `json:"message"`
	} `json:"events"`
}

func LineWebhook(db *pgxpool.Pool) gin.HandlerFunc {
	secret := os.Getenv("LINE_CHANNEL_SECRET")

	return func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "read body error"})
			return
		}

		signature := c.GetHeader("X-Line-Signature")
		if signature == "" {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "missing signature"})
			return
		}

		mac := hmac.New(sha256.New, []byte(secret))
		mac.Write(body)
		expectedMAC := mac.Sum(nil)
		expectedSignature := base64.StdEncoding.EncodeToString(expectedMAC)

		if signature != expectedSignature {
			log.Printf("LINE signature mismatch. Expected: %s..., Received: %s...", expectedSignature[:10], signature[:10])
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid signature"})
			return
		}

		var payload lineWebhookBody
		if err := json.Unmarshal(body, &payload); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid json"})
			return
		}

		for _, event := range payload.Events {
			if event.Type != "message" {
				continue // ignore non-message events silently
			}

			// 1. Identity Lookup
			var userIDStr string = event.Source.UserId
			var dbUserID uuid.UUID
			err = db.QueryRow(c.Request.Context(),
				"SELECT u.id FROM users u JOIN line_accounts la ON u.id = la.user_id WHERE la.line_id = $1",
				event.Source.UserId).Scan(&dbUserID)

			if err == nil {
				userIDStr = dbUserID.String()
			} else {
				log.Printf("LINE user not registered in line_accounts: %s, using raw ID as fallback", event.Source.UserId)
			}

			// 2. Message Parsing
			messageType := event.Message.Type
			text := event.Message.Text
			var attachment *model.Attachment

			switch messageType {
			case "image":
				sendLineMultimodalAck(db, "line", event.Source.UserId, "image")
				attachment, err = downloadLineContent(c.Request.Context(), userIDStr, event.Message.Id, "image.jpg", "image/jpeg")
			case "audio":
				messageType = "voice"
				sendLineMultimodalAck(db, "line", event.Source.UserId, "voice")
				attachment, err = downloadLineContent(c.Request.Context(), userIDStr, event.Message.Id, "audio.m4a", "audio/x-m4a")
				if attachment != nil {
					attachment.MediaType = "voice"
					attachment.DurationMs = event.Message.Duration
				}
			case "sticker":
				sendLineMultimodalAck(db, "line", event.Source.UserId, "image")
				attachment, err = downloadLineSticker(c.Request.Context(), userIDStr, event.Message.PackageId, event.Message.StickerId)
				if err != nil {
					log.Printf("Sticker download failed: %v", err)
					text = "[sticker: unavailable]"
					err = nil // Fallback to text placeholder
				} else {
					attachment.MediaType = "sticker"
				}
			}

			if err != nil {
				log.Printf("Content download failed: %v", err)
				// Continue with text only or error
			}

			msgId := uuid.New().String()
			stdMsg := model.StandardMessage{
				ID:              msgId,
				SourceMessageID: event.Message.Id,
				Platform:        "line",
				UserID:          userIDStr,
				MessageType:     messageType,
				Text:            text,
				Attachment:      attachment,
			}

			payloadJSON, _ := json.Marshal(stdMsg)

			_, err = db.Exec(c.Request.Context(),
				"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
				msgId, payloadJSON, 5, "pending")
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "db error"})
				return
			}

			// 4. Workspace Logging
			if attachment != nil && dbUserID != uuid.Nil {
				_, err = db.Exec(c.Request.Context(),
					"INSERT INTO file_workspace_log (local_path, user_id) VALUES ($1, $2) ON CONFLICT (local_path) DO UPDATE SET last_accessed_at = NOW()",
					attachment.LocalPath, dbUserID)
				if err != nil {
					log.Printf("Workspace log error: %v", err)
				}
			}
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}

func sendLineMultimodalAck(db *pgxpool.Pool, platform, lineID, modality string) {
	lineAckLock.Lock()
	defer lineAckLock.Unlock()

	lastAck, ok := lineAckMap[lineID]
	if ok && time.Since(lastAck) < 5*time.Second {
		return
	}

	var ackText string
	switch modality {
	case "voice":
		ackText = "嗯,收到了,正在聽..."
	case "image", "sticker":
		ackText = "嗯,收到了,正在看..."
	default:
		ackText = "嗯,收到了,正在看..."
	}

	messenger.SendReply(db, platform, lineID, ackText)
	lineAckMap[lineID] = time.Now()
}

func downloadLineContent(ctx context.Context, userID, messageID, fileName, mimeType string) (*model.Attachment, error) {
	token := os.Getenv("LINE_CHANNEL_ACCESS_TOKEN")
	url := fmt.Sprintf("https://api-data.line.me/v2/bot/message/%s/content", messageID)

	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("LINE content API error: %d", resp.StatusCode)
	}

	// Size limit check (10MB)
	if resp.ContentLength > 10*1024*1024 {
		return nil, fmt.Errorf("檔案大小超過 10MB 限制")
	}

	return saveToWorkspace(userID, fileName, mimeType, resp.Body)
}

func downloadLineSticker(ctx context.Context, userID, packageID, stickerID string) (*model.Attachment, error) {
	// LINE CDN pattern for stickers: https://stickershop.line-scdn.net/stickershop/v1/sticker/{stickerId}/iphone/sticker@2x.png
	url := fmt.Sprintf("https://stickershop.line-scdn.net/stickershop/v1/sticker/%s/iphone/sticker@2x.png", stickerID)

	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("LINE sticker CDN error: %d", resp.StatusCode)
	}

	return saveToWorkspace(userID, fmt.Sprintf("sticker_%s.png", stickerID), "image/png", resp.Body)
}

func saveToWorkspace(userID, fileName, mimeType string, body io.Reader) (*model.Attachment, error) {
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

	n, err := io.Copy(out, body)
	if err != nil {
		return nil, err
	}

	return &model.Attachment{
		FileID:    "line_content",
		FileName:  fileName,
		MimeType:  mimeType,
		SizeBytes: n,
		LocalPath: localPath,
	}, nil
}
