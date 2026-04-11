package handler

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"

	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type lineWebhookBody struct {
	Events []struct {
		Type   string `json:"type"`
		Source struct {
			UserId string `json:"userId"`
		} `json:"source"`
		Message struct {
			Type string `json:"type"`
			Text string `json:"text"`
			Id   string `json:"id"`
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
			msgId := uuid.New().String()
			stdMsg := model.StandardMessage{
				ID:          msgId,
				Platform:    "line",
				UserID:      event.Source.UserId,
				MessageType: event.Message.Type,
				Text:        event.Message.Text,
			}

			payloadJSON, _ := json.Marshal(stdMsg)

			_, err := db.Exec(c.Request.Context(), 
				"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
				msgId, payloadJSON, 5, "pending")
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "db error"})
				return
			}
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}
