package messenger

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"io"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	lineReplyURL   = "https://api.line.me/v2/bot/message/reply"
	linePushURL    = "https://api.line.me/v2/bot/message/push"
	lineLoadingURL = "https://api.line.me/v2/bot/chat/loading/start"

	// LINE 單則泡泡上限 5000 字，保守切 4500（同 hermes 策略）。
	lineChunkSize = 4500
	// LINE Reply/Push 單次 API call 最多 5 個訊息物件。
	lineBatchSize = 5
	// Telegram 單則上限 4096 UTF-16 code units，保守切 4000。
	telegramChunkSize = 4000
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

// DeliveryError 區分「可重試」（網路層 / 5xx / 429）與「終局」（其餘 4xx、設定錯誤）的投遞失敗，
// 供 forwarder 決定退避重試或進 dead-letter（undeliverable）。
type DeliveryError struct {
	StatusCode int   // 平台 HTTP status；0 表示傳輸層錯誤（無 HTTP 回應）
	Retryable  bool  // 是否值得退避後重試
	Err        error // 底層錯誤
}

func (e *DeliveryError) Error() string {
	if e.StatusCode == 0 {
		return fmt.Sprintf("delivery failed (network, retryable=%v): %v", e.Retryable, e.Err)
	}
	return fmt.Sprintf("delivery failed (status %d, retryable=%v): %v", e.StatusCode, e.Retryable, e.Err)
}

func (e *DeliveryError) Unwrap() error { return e.Err }

// retryableStatus：429 與 5xx 視為暫時性可重試；其餘 4xx 為終局。
func retryableStatus(code int) bool {
	return code == http.StatusTooManyRequests || code >= 500
}

// newHTTPDeliveryError 由平台回應 status 建構分類錯誤。
func newHTTPDeliveryError(code int, body string) *DeliveryError {
	return &DeliveryError{StatusCode: code, Retryable: retryableStatus(code),
		Err: fmt.Errorf("API status %d: %s", code, body)}
}

// newNetworkDeliveryError：傳輸層錯誤（逾時、連線失敗等，無 HTTP 回應），預設可重試。
func newNetworkDeliveryError(err error) *DeliveryError {
	return &DeliveryError{StatusCode: 0, Retryable: true, Err: err}
}

// IsRetryable 從任意投遞錯誤萃取可重試判定。非 DeliveryError（如設定缺失、unsupported platform）
// 保守視為終局（false），避免對結構性錯誤無限重試。
func IsRetryable(err error) bool {
	var de *DeliveryError
	if errors.As(err, &de) {
		return de.Retryable
	}
	return false
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

// chunkTextUTF16 以 UTF-16 code unit 計數切段（Telegram 的長度單位）：
// BMP 字元算 1、輔助平面（emoji 等）算 2。
func chunkTextUTF16(text string, size int) []string {
	var chunks []string
	var buf []rune
	count := 0
	for _, r := range text {
		units := 1
		if r > 0xFFFF {
			units = 2
		}
		if count+units > size && len(buf) > 0 {
			chunks = append(chunks, string(buf))
			buf = buf[:0]
			count = 0
		}
		buf = append(buf, r)
		count += units
	}
	if len(buf) > 0 {
		chunks = append(chunks, string(buf))
	}
	if len(chunks) == 0 {
		return []string{text}
	}
	return chunks
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
// 同樣套用切段；超過首批 5 則的部分改 Push。quoteToken 非空時首段帶引用框。
func SendLineReplyText(replyToken, lineID, text, quoteToken string) error {
	return sendLineText(lineID, text, &SendOptions{
		ReplyToken:          replyToken,
		ReplyTokenExpiresAt: time.Now().Add(50 * time.Second).Unix(),
		QuoteToken:          quoteToken,
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

// SendLineLoading 觸發 LINE 的 loading 動畫指示器（免費、不佔訊息額度）。
// 僅支援 1:1（chat_id 開頭 U），最長 60 秒，bot 回覆時自動消失。
// best-effort：失敗只記 log，絕不影響訊息處理流程。
func SendLineLoading(lineID string) {
	if !strings.HasPrefix(lineID, "U") {
		return
	}
	body := struct {
		ChatID         string `json:"chatId"`
		LoadingSeconds int    `json:"loadingSeconds"`
	}{ChatID: lineID, LoadingSeconds: 60}
	if err := postLineAPI(lineLoadingURL, body); err != nil {
		log.Printf("LINE: loading indicator failed (non-fatal): %v", err)
	}
}

// ---------------------------------------------------------------------------
// Telegram 輸入中指示器
// sendChatAction 平台端約 5 秒過期，需迴圈刷新（同 hermes _keep_typing 策略）。
// registry 為暫態（in-memory）：gateway 重啟遺失只是指示器消失，可接受。
// ---------------------------------------------------------------------------

var (
	typingMu    sync.Mutex
	typingStops = map[string]chan struct{}{}
)

const (
	typingRefreshInterval = 4 * time.Second
	typingMaxDuration     = 90 * time.Second
)

// SendTelegramTypingOnce 發送單次輸入中指示（約 5 秒），供下載附件等
// 入 queue 前的空窗使用，無需配對 Stop。
func SendTelegramTypingOnce(chatID string) {
	sendTelegramChatAction(chatID)
}

// StartTelegramTyping 啟動輸入中刷新迴圈，至 StopTyping(msgId) 或 90 秒上限。
func StartTelegramTyping(msgId, chatID string) {
	stop := make(chan struct{})
	typingMu.Lock()
	if old, ok := typingStops[msgId]; ok {
		close(old)
	}
	typingStops[msgId] = stop
	typingMu.Unlock()

	go func() {
		defer func() {
			typingMu.Lock()
			if typingStops[msgId] == stop {
				delete(typingStops, msgId)
			}
			typingMu.Unlock()
		}()
		deadline := time.NewTimer(typingMaxDuration)
		defer deadline.Stop()
		ticker := time.NewTicker(typingRefreshInterval)
		defer ticker.Stop()

		sendTelegramChatAction(chatID)
		for {
			select {
			case <-stop:
				return
			case <-deadline.C:
				return
			case <-ticker.C:
				sendTelegramChatAction(chatID)
			}
		}
	}()
}

// StopTyping 停止指定訊息的輸入中刷新（投遞完成或失敗時呼叫）。
// 未啟動過或已停止時為 no-op。
func StopTyping(msgId string) {
	typingMu.Lock()
	defer typingMu.Unlock()
	if stop, ok := typingStops[msgId]; ok {
		delete(typingStops, msgId)
		close(stop)
	}
}

func sendTelegramChatAction(chatID string) {
	token := os.Getenv("TELEGRAM_BOT_TOKEN")
	if token == "" {
		return
	}
	url := fmt.Sprintf("https://api.telegram.org/bot%s/sendChatAction", token)
	payload := map[string]string{"chat_id": chatID, "action": "typing"}
	jsonBody, _ := json.Marshal(payload)

	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Post(url, "application/json", bytes.NewBuffer(jsonBody))
	if err != nil {
		return // best-effort：網路慢就放棄這一拍，下一拍照常
	}
	resp.Body.Close()
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
		return newNetworkDeliveryError(err)
	}
	defer resp.Body.Close()

	// loading/start 成功回 202 Accepted，其餘 API 回 200 — 2xx 一律視為成功
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return newHTTPDeliveryError(resp.StatusCode, string(respBody))
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

	var firstErr error
	for i, chunk := range chunkTextUTF16(text, telegramChunkSize) {
		payload := map[string]any{
			"chat_id": chatID,
			"text":    chunk,
		}
		// reply 標注只掛首段（hermes 的 "first" 模式），避免一串重複引用框。
		// allow_sending_without_reply：原訊息被刪時自動退化為普通訊息，免重試。
		if i == 0 && opts != nil && opts.ReplyToMessageID != "" {
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
			if firstErr == nil {
				firstErr = newNetworkDeliveryError(err)
			}
			continue
		}
		if resp.StatusCode != http.StatusOK {
			respBody, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if firstErr == nil {
				firstErr = newHTTPDeliveryError(resp.StatusCode, string(respBody))
			}
			continue
		}
		resp.Body.Close()
	}

	return firstErr
}
