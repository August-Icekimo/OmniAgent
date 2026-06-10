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
	"strconv"
	"strings"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type lineWebhookBody struct {
	Events []struct {
		Type       string `json:"type"`
		ReplyToken string `json:"replyToken"`
		Source     struct {
			UserId string `json:"userId"`
		} `json:"source"`
		Message struct {
			Type       string `json:"type"`
			Text       string `json:"text"`
			Id         string `json:"id"`
			PackageId  string `json:"packageId"`
			StickerId  string `json:"stickerId"`
			Duration   int    `json:"duration"`
			QuoteToken string `json:"quoteToken"`
		} `json:"message"`
		Postback struct {
			Data string `json:"data"`
		} `json:"postback"`
	} `json:"events"`
}

// lineReplyTokenTTL：官方約 60 秒，保守取 50 秒（同 hermes 策略）。
const lineReplyTokenTTL = 50 * time.Second

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
			if event.Type == "postback" {
				handleLinePostback(db, event.Source.UserId, event.ReplyToken, event.Postback.Data)
				continue
			}
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

			// 即時回饋：loading 動畫（免費，bot 回覆時自動消失，僅 DM 有效）
			go messenger.SendLineLoading(event.Source.UserId)

			// 2. Message Parsing
			messageType := event.Message.Type
			text := event.Message.Text
			var attachment *model.Attachment

			switch messageType {
			case "image":
				attachment, err = downloadLineContent(c.Request.Context(), userIDStr, event.Message.Id, "image.jpg", "image/jpeg")
			case "audio":
				messageType = "voice"
				attachment, err = downloadLineContent(c.Request.Context(), userIDStr, event.Message.Id, "audio.m4a", "audio/x-m4a")
				if attachment != nil {
					attachment.MediaType = "voice"
					attachment.DurationMs = event.Message.Duration
				}
			case "sticker":
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
				ReplyToken:      event.ReplyToken,
				QuoteToken:      event.Message.QuoteToken,
			}
			if event.ReplyToken != "" {
				stdMsg.ReplyTokenExpiresAt = time.Now().Add(lineReplyTokenTTL).Unix()
			}

			payloadJSON, marshalErr := json.Marshal(stdMsg)
			if marshalErr != nil {
				log.Printf("Marshal error for LINE message: %v", marshalErr)
				c.JSON(http.StatusInternalServerError, gin.H{"error": "marshal error"})
				return
			}

			_, err = db.Exec(c.Request.Context(),
				"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
				msgId, payloadJSON, 5, "pending")
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "db error"})
				return
			}

			// 慢回應監看：超過門檻仍未投遞時，燒掉 reply token 送 postback 按鈕
			if event.ReplyToken != "" {
				go monitorSlowLineReply(db, msgId, event.Source.UserId, event.ReplyToken, stdMsg.ReplyTokenExpiresAt, stdMsg.QuoteToken)
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

// slowLineThreshold 讀取慢回應門檻（秒）。0 或負值表示停用 postback 按鈕機制。
func slowLineThreshold() time.Duration {
	raw := os.Getenv("LINE_SLOW_THRESHOLD_SECONDS")
	if raw == "" {
		return 45 * time.Second
	}
	sec, err := strconv.Atoi(raw)
	if err != nil || sec <= 0 {
		return 0
	}
	return time.Duration(sec) * time.Second
}

// monitorSlowLineReply 在門檻到點時檢查訊息是否已投遞；尚未投遞且 reply token
// 仍有效，就建立 pending 列並燒掉 token 送「取得答案」按鈕。
// 與 forwarder 的競態由 token 單次使用特性自然解決：若 forwarder 已用 token
// 直接投遞，這裡的按鈕送出會被 LINE API 拒絕，pending 列隨即清掉。
func monitorSlowLineReply(db *pgxpool.Pool, msgId, lineID, replyToken string, expiresAt int64, quoteToken string) {
	threshold := slowLineThreshold()
	if threshold <= 0 {
		return
	}
	time.Sleep(threshold)

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	// 已投遞（或失敗已回報）就不打擾
	var status string
	if err := db.QueryRow(ctx, "SELECT status FROM message_queue WHERE id = $1", msgId).Scan(&status); err != nil {
		return
	}
	if status == "done" || status == "failed" {
		return
	}
	// token 已過期就只能靠 forwarder 的 Push fallback
	if time.Now().Unix() >= expiresAt {
		return
	}

	var rid string
	err := db.QueryRow(ctx,
		"INSERT INTO line_pending_replies (line_id, quote_token) VALUES ($1, NULLIF($2, '')) RETURNING rid",
		lineID, quoteToken).Scan(&rid)
	if err != nil {
		log.Printf("LINE: pending reply insert failed: %v", err)
		return
	}

	if err := messenger.SendLineSlowReplyButton(replyToken, rid); err != nil {
		// token 多半已被正常投遞消耗，清掉孤兒列
		log.Printf("LINE: slow-reply button send failed (%v); removing pending row %s", err, rid)
		_, _ = db.Exec(ctx, "DELETE FROM line_pending_replies WHERE rid = $1 AND state = 'pending'", rid)
		return
	}
	log.Printf("LINE: sent slow-reply postback button for chat %s (rid=%s)", lineID, rid)
}

// handleLinePostback 處理「取得答案」按鈕點擊：以 postback 帶來的新 reply token
// 投遞快取答案。狀態機：pending → ready → delivered，失敗為 error。
func handleLinePostback(db *pgxpool.Pool, lineID, replyToken, data string) {
	if !strings.HasPrefix(data, "rid=") {
		log.Printf("LINE: postback with unrecognized data: %q", data)
		return
	}
	rid := strings.TrimPrefix(data, "rid=")
	if rid == "" {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	// 原子認領：只有 ready 列會轉 delivered 並取得 payload 與原訊息引用 token
	var payload string
	var quoteToken *string
	err := db.QueryRow(ctx,
		"UPDATE line_pending_replies SET state = 'delivered', updated_at = NOW() WHERE rid = $1 AND state = 'ready' RETURNING payload, quote_token",
		rid).Scan(&payload, &quoteToken)
	if err == nil {
		qt := ""
		if quoteToken != nil {
			qt = *quoteToken
		}
		// SendLineReplyText 內建 reply→push fallback，標記 delivered 後不會丟失
		if sendErr := messenger.SendLineReplyText(replyToken, lineID, payload, qt); sendErr != nil {
			log.Printf("LINE: postback delivery failed for rid %s: %v", rid, sendErr)
		}
		return
	}

	// 非 ready：依現況回覆提示
	var state string
	var hint string
	if scanErr := db.QueryRow(ctx, "SELECT state FROM line_pending_replies WHERE rid = $1", rid).Scan(&state); scanErr != nil {
		hint = "這個按鈕已經過期了，麻煩再問我一次。"
	} else {
		switch state {
		case "pending":
			hint = "我還在想這題，好了之後你再點一次按鈕。"
		case "delivered":
			hint = "這個答案剛剛已經送過囉。"
		default: // error
			hint = "剛才處理的時候出了點狀況，麻煩再問我一次。"
		}
	}
	if sendErr := messenger.SendLineReplyText(replyToken, lineID, hint, ""); sendErr != nil {
		log.Printf("LINE: postback hint send failed for rid %s: %v", rid, sendErr)
	}
}

func downloadLineContent(ctx context.Context, userID, messageID, fileName, mimeType string) (*model.Attachment, error) {
	token := os.Getenv("LINE_CHANNEL_ACCESS_TOKEN")
	url := fmt.Sprintf("https://api-data.line.me/v2/bot/message/%s/content", messageID)

	dlCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(dlCtx, "GET", url, nil)
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

	dlCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(dlCtx, "GET", url, nil)
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
