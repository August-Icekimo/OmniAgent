package messenger

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"io"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	lineReplyURL = "https://api.line.me/v2/bot/message/reply"
	linePushURL  = "https://api.line.me/v2/bot/message/push"

	// LINE 單則泡泡上限 5000 字，保守切 4500（同 hermes 策略）。
	lineChunkSize = 4500
	// LINE Reply/Push 單次 API call 最多 5 個訊息物件。
	lineBatchSize = 5
)

// SendOptions 攜帶單次投遞的平台提示。零值（或 nil）行為等同舊版純 Push。
type SendOptions struct {
	ReplyToken          string // LINE：免費 Reply API 的單次 token
	ReplyTokenExpiresAt int64  // unix 秒；0 視為不可用
	QuoteToken          string // LINE：帶上可在回覆顯示引用框
	ReplyToMessageID    string // Telegram：標注回覆的原訊息 id
}

func (o *SendOptions) replyTokenUsable() bool {
	return o != nil && o.ReplyToken != "" && time.Now().Unix() < o.ReplyTokenExpiresAt
}

// SendReply delivers a text message back to the specified platform and user.
// It handles resolving internal UUIDs to platform-specific IDs if necessary.
func SendReply(db *pgxpool.Pool, platform, userID, text string) error {
	return SendReplyWithOptions(db, platform, userID, text, nil)
}

// SendReplyWithOptions 同 SendReply，但可帶 reply token / 引用等投遞提示。
func SendReplyWithOptions(db *pgxpool.Pool, platform, userID, text string, opts *SendOptions) error {
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
		return sendLineText(targetID, text, opts)
	case "telegram":
		return sendTelegramMessage(targetID, text, opts)
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

// ---------------------------------------------------------------------------
// LINE
// ---------------------------------------------------------------------------

type lineMessage struct {
	Type       string `json:"type"`
	Text       string `json:"text,omitempty"`
	QuoteToken string `json:"quoteToken,omitempty"`

	// Template Buttons（慢回應 postback 用），與 Text 互斥
	AltText  string        `json:"altText,omitempty"`
	Template *lineTemplate `json:"template,omitempty"`
}

type lineTemplate struct {
	Type    string       `json:"type"`
	Text    string       `json:"text"`
	Actions []lineAction `json:"actions"`
}

type lineAction struct {
	Type  string `json:"type"`
	Label string `json:"label"`
	Data  string `json:"data"`
}

// chunkText 以 rune 為單位切段，避免在多位元組字元中間斷開。
func chunkText(text string, size int) []string {
	runes := []rune(text)
	if len(runes) <= size {
		return []string{text}
	}
	var chunks []string
	for start := 0; start < len(runes); start += size {
		end := start + size
		if end > len(runes) {
			end = len(runes)
		}
		chunks = append(chunks, string(runes[start:end]))
	}
	return chunks
}

// sendLineText 切段並投遞：首批優先 Reply（免費），失敗或 token 不可用則 Push；
// 後續批次一律 Push（reply token 單次使用）。
func sendLineText(lineID, text string, opts *SendOptions) error {
	var messages []lineMessage
	for i, chunk := range chunkText(text, lineChunkSize) {
		m := lineMessage{Type: "text", Text: chunk}
		if i == 0 && opts != nil {
			m.QuoteToken = opts.QuoteToken
		}
		messages = append(messages, m)
	}

	var firstErr error
	for start := 0; start < len(messages); start += lineBatchSize {
		end := start + lineBatchSize
		if end > len(messages) {
			end = len(messages)
		}
		batch := messages[start:end]

		if start == 0 && opts.replyTokenUsable() {
			if err := SendLineReply(opts.ReplyToken, batch); err == nil {
				log.Printf("LINE: delivered batch via reply token")
				continue
			} else {
				log.Printf("LINE: reply token rejected (%v); falling back to push", err)
			}
		}
		if err := sendLinePushMessages(lineID, batch); err != nil {
			if firstErr == nil {
				firstErr = err
			}
			log.Printf("LINE: push send failed: %v", err)
		}
	}
	return firstErr
}

// SendLineReply 以 reply token 投遞訊息（單次使用、免費）。
func SendLineReply(replyToken string, messages []lineMessage) error {
	body := struct {
		ReplyToken string        `json:"replyToken"`
		Messages   []lineMessage `json:"messages"`
	}{ReplyToken: replyToken, Messages: messages}
	return postLineAPI(lineReplyURL, body)
}

// SendLineReplyText 是 SendLineReply 的純文字便利包裝（postback 回覆用），
// 同樣套用切段；超過首批 5 則的部分改 Push。
func SendLineReplyText(replyToken, lineID, text string) error {
	return sendLineText(lineID, text, &SendOptions{
		ReplyToken:          replyToken,
		ReplyTokenExpiresAt: time.Now().Add(50 * time.Second).Unix(),
	})
}

// SendLineSlowReplyButton 以 reply token 送出「取得答案」postback 按鈕。
// LLM 超過慢回應門檻時，與其讓 token 白白過期，不如燒掉它換一次免費投遞機會：
// 使用者點按鈕時 postback event 會帶來全新的 reply token。
func SendLineSlowReplyButton(replyToken, rid string) error {
	msg := lineMessage{
		Type:    "template",
		AltText: "我還在思考中，準備好後點按鈕取得答案。",
		Template: &lineTemplate{
			Type: "buttons",
			Text: "這題我需要多想一下。準備好後，點下方按鈕取得答案。",
			Actions: []lineAction{
				{Type: "postback", Label: "取得答案", Data: "rid=" + rid},
			},
		},
	}
	return SendLineReply(replyToken, []lineMessage{msg})
}

// ResolveLineID 將內部 UUID 解析為 LINE 平台 ID（U 開頭）；
// 非 UUID（已是平台 ID）原樣回傳。
func ResolveLineID(db *pgxpool.Pool, userID string) string {
	if _, err := uuid.Parse(userID); err != nil {
		return userID
	}
	if resolved, err := resolvePlatformID(db, "line", userID); err == nil {
		return resolved
	}
	return userID
}

func sendLinePushMessages(lineID string, messages []lineMessage) error {
	body := struct {
		To       string        `json:"to"`
		Messages []lineMessage `json:"messages"`
	}{To: lineID, Messages: messages}
	return postLineAPI(linePushURL, body)
}

func postLineAPI(url string, payload any) error {
	token := os.Getenv("LINE_CHANNEL_ACCESS_TOKEN")
	if token == "" {
		return fmt.Errorf("LINE_CHANNEL_ACCESS_TOKEN not set")
	}

	jsonBody, _ := json.Marshal(payload)
	req, _ := http.NewRequest("POST", url, bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{Timeout: 10 * time.Second}
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

// ---------------------------------------------------------------------------
// Telegram
// ---------------------------------------------------------------------------

func sendTelegramMessage(chatID, text string, opts *SendOptions) error {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		return fmt.Errorf("TELEGRAM_BOT_TOKEN not set")
	}

	url := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", token)

	payload := map[string]any{
		"chat_id": chatID,
		"text":    text,
	}
	// allow_sending_without_reply：原訊息被刪時自動退化為普通訊息，免重試。
	if opts != nil && opts.ReplyToMessageID != "" {
		if msgID, err := strconv.Atoi(opts.ReplyToMessageID); err == nil {
			payload["reply_parameters"] = map[string]any{
				"message_id":                  msgID,
				"allow_sending_without_reply": true,
			}
		}
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
