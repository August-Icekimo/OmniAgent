package handler

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"

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
			FileID string `json:"file_id"`
		} `json:"photo"`
	} `json:"message"`
}

func TelegramWebhook(db *pgxpool.Pool) gin.HandlerFunc {
	webhookSecret := os.Getenv("TELEGRAM_WEBHOOK_SECRET")
	allowedChatsStr := os.Getenv("TELEGRAM_ALLOWED_CHAT_IDS")

	var allowedChatsList []string
	if allowedChatsStr != "" {
		for _, v := range strings.Split(allowedChatsStr, ",") {
			trimmed := strings.TrimSpace(v)
			if trimmed != "" {
				allowedChatsList = append(allowedChatsList, trimmed)
			}
		}
	} else {
		log.Println("TELEGRAM_ALLOWED_CHAT_IDS not set, all chats rejected")
	}

	return func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "read body error"})
			return
		}

		secretToken := c.GetHeader("X-Telegram-Bot-Api-Secret-Token")
		if secretToken == "" || secretToken != webhookSecret {
			log.Printf("Unauthorized Telegram webhook request, token mismatch")
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
			log.Println("Ignoring non-message update")
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		chatIDStr := strconv.FormatInt(payload.Message.Chat.ID, 10)

		// Verification of allowed chat IDs
		if len(allowedChatsList) == 0 {
			log.Println("Unauthorized chat_id (all rejected)")
			c.JSON(http.StatusOK, gin.H{"status": "unauthorized"})
			return
		}

		isAllowed := false
		for _, allowedID := range allowedChatsList {
			if chatIDStr == allowedID {
				isAllowed = true
				break
			}
		}

		if !isAllowed {
			log.Printf("Unauthorized chat_id: %s", chatIDStr)
			c.JSON(http.StatusOK, gin.H{"status": "unauthorized"})
			return
		}

		messageType := ""
		text := ""

		if payload.Message.Text != "" {
			messageType = "text"
			text = payload.Message.Text
		} else if len(payload.Message.Photo) > 0 {
			messageType = "image"
			// Text is intentionally empty; downloading image is Phase 4B
		} else {
			log.Println("Ignoring non-text/non-image message update")
			// Neither text nor image, ignore silently
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		msgId := uuid.New().String()
		stdMsg := model.StandardMessage{
			ID:          msgId,
			Platform:    "telegram",
			UserID:      chatIDStr,
			MessageType: messageType,
			Text:        text,
		}

		payloadJSON, _ := json.Marshal(stdMsg)

		_, err = db.Exec(c.Request.Context(),
			"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
			msgId, payloadJSON, 5, "pending")
		if err != nil {
			log.Printf("DB write error for telegram updates: %v", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "db error"})
			return
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}
