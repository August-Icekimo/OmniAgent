package handler

import (
	"encoding/json"
	"io"
	"net/http"
	"os"

	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type bluebubblesWebhookBody struct {
	Type string `json:"type"`
	Data struct {
		Text  string `json:"text"`
		Chats []struct {
			ChatIdentifier string `json:"chatIdentifier"`
		} `json:"chats"`
	} `json:"data"`
}

func BlueBubblesWebhook(db *pgxpool.Pool) gin.HandlerFunc {
	expectedPassword := os.Getenv("BLUEBUBBLES_PASSWORD")

	return func(c *gin.Context) {
		password := c.Query("password")
		if password == "" || password != expectedPassword {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
			return
		}

		body, err := io.ReadAll(c.Request.Body)
		if err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "read body error"})
			return
		}

		var payload bluebubblesWebhookBody
		if err := json.Unmarshal(body, &payload); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid json"})
			return
		}

		if payload.Type != "new-message" {
			// Silently ignore non-new-message events
			c.JSON(http.StatusOK, gin.H{"status": "ignored"})
			return
		}

		userId := ""
		if len(payload.Data.Chats) > 0 {
			userId = payload.Data.Chats[0].ChatIdentifier
		}

		msgId := uuid.New().String()
		stdMsg := model.StandardMessage{
			ID:          msgId,
			Platform:    "imessage",
			UserID:      userId,
			MessageType: "text",
			Text:        payload.Data.Text,
		}

		payloadJSON, _ := json.Marshal(stdMsg)

		_, err = db.Exec(c.Request.Context(),
			"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
			msgId, payloadJSON, 5, "pending")
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "db error"})
			return
		}

		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}
