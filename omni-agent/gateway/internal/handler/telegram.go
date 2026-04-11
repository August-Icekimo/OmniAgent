package handler

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"

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
			FileID string `json:"file_id"`
		} `json:"photo"`
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

		if payload.Message.Text != "" {
			messageType = "text"
			text = payload.Message.Text
		} else if len(payload.Message.Photo) > 0 {
			messageType = "image"
		} else {
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		// 3. Queue Message
		msgId := uuid.New().String()
		stdMsg := model.StandardMessage{
			ID:          msgId,
			Platform:    "telegram",
			UserID:      userID.String(), // Internal UUID
			MessageType: messageType,
			Text:        text,
		}

		payloadJSON, _ := json.Marshal(stdMsg)

		_, err = db.Exec(c.Request.Context(),
			"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
			msgId, payloadJSON, 5, "pending")
		if err != nil {
			log.Printf("DB write error for telegram updates: %v", err)
			c.JSON(http.StatusOK, gin.H{"error": "db error"}) // Still 200 to avoid TG retry
			return
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}
