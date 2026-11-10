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

type telegramUpdate struct {
	UpdateID      int                    `json:"update_id"`
	Message       *telegramMessage       `json:"message"`
	CallbackQuery *telegramCallbackQuery `json:"callback_query"`
}

// telegramCallbackQuery：使用者點 Inline Keyboard 按鈕（reply-quick-options）。
// Data 為按鈕要以使用者身分送出的文字；Message 為帶按鈕的那則 bot 訊息。
type telegramCallbackQuery struct {
	ID   string `json:"id"`
	From struct {
		ID int64 `json:"id"`
	} `json:"from"`
	Message *struct {
		MessageID int `json:"message_id"`
		Chat      struct {
			ID int64 `json:"id"`
		} `json:"chat"`
	} `json:"message"`
	Data string `json:"data"`
}

type telegramMessage struct {
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

		// 按鈕點擊：轉成「使用者送出按鈕文字」的一般文字訊息，走下方同一條流程
		if payload.Message == nil && payload.CallbackQuery != nil {
			msg, ok := callbackToMessage(c.Request.Context(), db, payload.CallbackQuery)
			if !ok {
				c.JSON(http.StatusOK, gin.H{"status": "callback_ignored"})
				return
			}
			payload.Message = msg
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

		// 即時回饋：單次輸入中指示（約 5 秒），覆蓋附件下載空窗；
		// 入 queue 後由 StartTelegramTyping 的刷新迴圈接手。
		go messenger.SendTelegramTypingOnce(chatIDStr)

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
					os.Remove(attachment.LocalPath)
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

		payloadJSON, marshalErr := json.Marshal(stdMsg)
		if marshalErr != nil {
			log.Printf("Marshal error for telegram message: %v", marshalErr)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "marshal error"})
			return
		}

		_, err = db.Exec(c.Request.Context(),
			"INSERT INTO message_queue (id, payload, priority, status) VALUES ($1, $2, $3, $4)",
			msgId, payloadJSON, 5, "pending")
		if err != nil {
			log.Printf("DB write error for telegram updates: %v", err)
			c.JSON(http.StatusOK, gin.H{"error": "db error"})
			return
		}

		// 輸入中刷新迴圈：至 forwarder 投遞完成（StopTyping）或 90 秒上限
		messenger.StartTelegramTyping(msgId, chatIDStr)

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
	getCtx, getCancel := context.WithTimeout(ctx, 5*time.Second)
	defer getCancel()
	getReq, err := http.NewRequestWithContext(getCtx, "GET", getFilePathURL, nil)
	if err != nil {
		return nil, err
	}
	resp, err := http.DefaultClient.Do(getReq)
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

// ---------------------------------------------------------------------------
// Inline Keyboard 按鈕點擊（reply-quick-options）
// ---------------------------------------------------------------------------

// 同一則 bot 訊息的按鈕只認第一次點擊：移除按鈕的 API 呼叫前若連點，第二次在此被擋下。
// in-memory 即可：gateway 單一行程；重啟後按鈕早已移除，遺失 registry 無影響。
var (
	callbackClaimMu sync.Mutex
	callbackClaims  = map[string]time.Time{}
)

const callbackClaimTTL = 10 * time.Minute

func claimCallbackMessage(chatID int64, messageID int) bool {
	key := fmt.Sprintf("%d:%d", chatID, messageID)
	now := time.Now()
	callbackClaimMu.Lock()
	defer callbackClaimMu.Unlock()
	for k, t := range callbackClaims {
		if now.Sub(t) > callbackClaimTTL {
			delete(callbackClaims, k)
		}
	}
	if _, taken := callbackClaims[key]; taken {
		return false
	}
	callbackClaims[key] = now
	return true
}

// callbackToMessage 處理按鈕點擊：一律 answerCallbackQuery（否則按鈕持續轉圈）；
// 僅已知使用者、首次點擊才移除按鈕並轉成文字訊息。陌生人／未知 chat 不處理也不回覆。
func callbackToMessage(ctx context.Context, db *pgxpool.Pool, cq *telegramCallbackQuery) (*telegramMessage, bool) {
	go messenger.AnswerTelegramCallback(cq.ID)

	if cq.Message == nil || cq.Data == "" {
		return nil, false
	}
	chatID := cq.Message.Chat.ID
	var role string
	err := db.QueryRow(ctx,
		"SELECT u.role FROM users u JOIN telegram_accounts ta ON u.id = ta.user_id WHERE ta.chat_id = $1",
		strconv.FormatInt(chatID, 10)).Scan(&role)
	if err != nil || role == "stranger" {
		log.Printf("Telegram: callback from unknown chat %d ignored", chatID)
		return nil, false
	}
	if !claimCallbackMessage(chatID, cq.Message.MessageID) {
		log.Printf("Telegram: duplicate callback on message %d ignored", cq.Message.MessageID)
		return nil, false
	}
	go messenger.RemoveTelegramInlineKeyboard(strconv.FormatInt(chatID, 10), cq.Message.MessageID)

	msg := &telegramMessage{MessageID: cq.Message.MessageID, Text: cq.Data}
	msg.From.ID = cq.From.ID
	msg.Chat.ID = chatID
	return msg, true
}
