package messenger

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"

	"io"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

// SendReply delivers a text message back to the specified platform and user.
// It handles resolving internal UUIDs to platform-specific IDs if necessary.
func SendReply(db *pgxpool.Pool, platform, userID, text string) error {
	var targetID string = userID

	// 1. Resolve Identity if userID is a UUID
	if _, err := uuid.Parse(userID); err == nil {
		resolvedID, err := resolvePlatformID(db, platform, userID)
		if err == nil {
			targetID = resolvedID
		} else {
			log.Printf("Warning: Failed to resolve platform ID for UUID %s on %s: %v", userID, platform, err)
			// Fallback: use userID as is (it might be a platform ID already if things are inconsistent)
		}
	}

	// 2. Route to platform-specific messenger
	switch platform {
	case "line":
		return sendLinePush(targetID, text)
	case "telegram":
		return sendTelegramMessage(targetID, text)
	default:
		return fmt.Errorf("unsupported platform: %s", platform)
	}
}

func resolvePlatformID(db *pgxpool.Pool, platform, userUUID string) (string, error) {
	var query string
	var resolvedID string

	switch platform {
	case "line":
		query = "SELECT line_id FROM line_accounts WHERE user_id = $1 LIMIT 1"
	case "telegram":
		query = "SELECT chat_id FROM telegram_accounts WHERE user_id = $1 LIMIT 1"
	default:
		return "", fmt.Errorf("unsupported platform for resolution: %s", platform)
	}

	err := db.QueryRow(context.Background(), query, userUUID).Scan(&resolvedID)
	if err != nil {
		return "", err
	}
	return resolvedID, nil
}

func sendLinePush(lineID, text string) error {
	token := os.Getenv("LINE_CHANNEL_ACCESS_TOKEN")
	if token == "" {
		return fmt.Errorf("LINE_CHANNEL_ACCESS_TOKEN not set")
	}

	url := "https://api.line.me/v2/bot/message/push"
	
	type lineMessage struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	type linePushBody struct {
		To       string        `json:"to"`
		Messages []lineMessage `json:"messages"`
	}

	body := linePushBody{
		To: lineID,
		Messages: []lineMessage{
			{Type: "text", Text: text},
		},
	}

	jsonBody, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("LINE API returned status %d: %s", resp.StatusCode, string(respBody))
	}

	return nil
}

func sendTelegramMessage(chatID, text string) error {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		return fmt.Errorf("TELEGRAM_BOT_TOKEN not set")
	}

	url := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", token)
	
	payload := map[string]string{
		"chat_id": chatID,
		"text":    text,
	}

	jsonBody, _ := json.Marshal(payload)
	resp, err := http.Post(url, "application/json", bytes.NewBuffer(jsonBody))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("Telegram API returned status %d: %s", resp.StatusCode, string(respBody))
	}

	return nil
}

