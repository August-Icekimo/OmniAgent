package forwarder

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"omni-agent/gateway/internal/messenger"
	"omni-agent/gateway/internal/model"

	"github.com/jackc/pgx/v5/pgxpool"
)

// turn 組裝設定。DB 驅動（單一 forwarder 迴圈，但 deadline 落 DB 以求 crash-safe）。
//   - silence：每來一則訊息重置的靜默窗（reset-on-each）。
//   - ceiling：自首訊息起的硬上限，防慢打字者餓死。
func turnSilenceSeconds() int { return envInt("TURN_SILENCE_SECONDS", 4) }
func turnCeilingSeconds() int { return envInt("TURN_CEILING_SECONDS", 30) }

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return def
}

// turnPayload 是送往 brain /turn 的解耦請求：一個 turn 含其組裝起來的多則訊息。
type turnPayload struct {
	TurnID   string            `json:"turn_id"`
	UserID   string            `json:"user_id"`
	Platform string            `json:"platform"`
	Messages []json.RawMessage `json:"messages"`
}

// assembleTurns 把待處理、尚未歸入 turn 的訊息收斂進使用者的組裝中 turn。
// per-user 序列化由 turns_one_active_per_user（partial unique index）保證：
// 使用者有 processing turn 時不會建立新的組裝 turn，訊息留 pending 等下一回合。
func assembleTurns(db *pgxpool.Pool) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	silence := turnSilenceSeconds()
	ceiling := turnCeilingSeconds()

	// 1. 反正規化 user_id（供 per-user 收斂查詢；payload 內已是 users.id UUID）。
	if _, err := db.Exec(ctx, `
		UPDATE message_queue
		SET user_id = (payload->>'user_id')::uuid
		WHERE status = 'pending' AND user_id IS NULL
		  AND payload->>'user_id' IS NOT NULL AND payload->>'user_id' <> ''
	`); err != nil {
		log.Printf("turn assemble: backfill user_id failed: %v", err)
		return
	}

	// 2. 為「有待處理散訊息、但目前無進行中 turn」的使用者建立組裝 turn。
	//    NOT EXISTS 在單一 forwarder 迴圈下足以避免重複建立；unique index 為防護網。
	if _, err := db.Exec(ctx, `
		INSERT INTO turns (user_id, platform, silence_deadline, hard_deadline)
		SELECT DISTINCT ON (mq.user_id)
		       mq.user_id,
		       mq.payload->>'platform',
		       NOW() + make_interval(secs => $1),
		       NOW() + make_interval(secs => $2)
		FROM message_queue mq
		WHERE mq.status = 'pending' AND mq.turn_id IS NULL AND mq.user_id IS NOT NULL
		  AND NOT EXISTS (
		      SELECT 1 FROM turns t
		      WHERE t.user_id = mq.user_id AND t.status IN ('assembling', 'processing')
		  )
		ORDER BY mq.user_id, mq.created_at ASC
	`, silence, ceiling); err != nil {
		log.Printf("turn assemble: create turns failed: %v", err)
		return
	}

	// 3. 把散訊息掛進組裝中 turn，並 bump 該 turn 的 silence_deadline（reset-on-each）。
	//    只對「本回合新掛入訊息」的 turn bump，故靜默窗只在真有新訊息時重置。
	if _, err := db.Exec(ctx, `
		WITH attached AS (
			UPDATE message_queue mq
			SET turn_id = t.id
			FROM turns t
			WHERE mq.status = 'pending' AND mq.turn_id IS NULL
			  AND t.user_id = mq.user_id AND t.status = 'assembling'
			RETURNING t.id
		)
		UPDATE turns
		SET silence_deadline = NOW() + make_interval(secs => $1), updated_at = NOW()
		WHERE id IN (SELECT DISTINCT id FROM attached) AND status = 'assembling'
	`, silence); err != nil {
		log.Printf("turn assemble: attach messages failed: %v", err)
	}
}

// dispatchDueTurn 取一個到期（靜默或封頂）的組裝 turn，轉 processing，
// 把整個 turn 的訊息打包送到 brain /turn（解耦：brain 非同步處理、寫回 turns.result）。
// 回傳 true 表示本回合處理了一個 turn。
func dispatchDueTurn(db *pgxpool.Pool, turnURL string) bool {
	ctx := context.Background()
	tx, err := db.Begin(ctx)
	if err != nil {
		return false
	}
	defer tx.Rollback(ctx)

	var turnID, userID, platform string
	err = tx.QueryRow(ctx, `
		UPDATE turns
		SET status = 'processing', updated_at = NOW()
		WHERE id = (
			SELECT id FROM turns
			WHERE status = 'assembling'
			  AND (NOW() >= silence_deadline OR NOW() >= hard_deadline)
			ORDER BY hard_deadline ASC
			FOR UPDATE SKIP LOCKED
			LIMIT 1
		)
		RETURNING id, user_id::text, platform
	`).Scan(&turnID, &userID, &platform)
	if err != nil {
		return false // 無到期 turn
	}

	// 收集此 turn 的訊息（依到達順序）。
	rows, err := tx.Query(ctx, `
		SELECT payload FROM message_queue
		WHERE turn_id = $1 ORDER BY created_at ASC
	`, turnID)
	if err != nil {
		log.Printf("turn dispatch: load messages failed (turn=%s): %v", turnID, err)
		return true
	}
	var messages []json.RawMessage
	for rows.Next() {
		var p []byte
		if err := rows.Scan(&p); err != nil {
			continue
		}
		messages = append(messages, json.RawMessage(p))
	}
	rows.Close()

	if len(messages) == 0 {
		// 空 turn（理論上不會發生）：直接收尾，避免卡住。
		_, _ = tx.Exec(ctx, "UPDATE turns SET status = 'failed', updated_at = NOW() WHERE id = $1", turnID)
		tx.Commit(ctx)
		return true
	}

	body, _ := json.Marshal(turnPayload{
		TurnID:   turnID,
		UserID:   userID,
		Platform: platform,
		Messages: messages,
	})

	log.Printf("turn dispatch: turn %s (user=%s, %d msgs) → %s", turnID, userID, len(messages), turnURL)
	resp, err := http.Post(turnURL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Printf("turn dispatch: brain POST failed (turn=%s): %v", turnID, err)
		failTurnLineReply(db, ctx, messages)
		_, _ = tx.Exec(ctx, "UPDATE turns SET status = 'failed', updated_at = NOW() WHERE id = $1", turnID)
		tx.Commit(ctx)
		return true
	}
	defer resp.Body.Close()

	// 解耦：brain 接受 turn 後回 202/200 立即返回，實際結果稍後寫入 turns.result。
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusAccepted {
		log.Printf("turn dispatch: brain returned %d (turn=%s)", resp.StatusCode, turnID)
		failTurnLineReply(db, ctx, messages)
		_, _ = tx.Exec(ctx, "UPDATE turns SET status = 'failed', updated_at = NOW() WHERE id = $1", turnID)
		tx.Commit(ctx)
		return true
	}

	tx.Commit(ctx)
	return true
}

// deliverDoneTurn 投遞一個 brain 已完成（status='done'、result 已寫）的 turn。
// 用該 turn 最後一則訊息的 reply token / 平台資訊投遞；完成後標 delivered。
func deliverDoneTurn(db *pgxpool.Pool) bool {
	ctx := context.Background()
	tx, err := db.Begin(ctx)
	if err != nil {
		return false
	}
	defer tx.Rollback(ctx)

	var turnID, userID, platform, result string
	err = tx.QueryRow(ctx, `
		SELECT id, user_id::text, platform, COALESCE(result, '')
		FROM turns
		WHERE status = 'done'
		ORDER BY updated_at ASC
		FOR UPDATE SKIP LOCKED
		LIMIT 1
	`).Scan(&turnID, &userID, &platform, &result)
	if err != nil {
		return false
	}

	// 取最後一則訊息作為投遞依據（最新 reply token 最不易過期）。
	var lastPayload []byte
	_ = tx.QueryRow(ctx, `
		SELECT payload FROM message_queue
		WHERE turn_id = $1 ORDER BY created_at DESC LIMIT 1
	`, turnID).Scan(&lastPayload)

	var lastMsg model.StandardMessage
	if lastPayload != nil {
		_ = json.Unmarshal(lastPayload, &lastMsg)
	}

	// 整個 turn 的輸入指示器收尾（Telegram）。
	stopTurnTyping(db, ctx, turnID)

	if result != "" {
		replyText := result // brain 端已含 footer（解耦後 footer 由 brain 組裝，見 Task 2）

		// 慢回應按鈕已送出：答案進快取，改由 postback 取件。
		if claimPendingLineReply(db, ctx, &lastMsg, replyText) {
			log.Printf("turn deliver: turn %s cached for LINE postback", turnID)
		} else {
			opts := &messenger.SendOptions{
				ReplyToken:          lastMsg.ReplyToken,
				ReplyTokenExpiresAt: lastMsg.ReplyTokenExpiresAt,
				QuoteToken:          lastMsg.QuoteToken,
			}
			if platform == "telegram" {
				opts.ReplyToMessageID = lastMsg.SourceMessageID
			}
			if err := messenger.SendReplyWithOptions(db, platform, userID, replyText, opts); err != nil {
				log.Printf("turn deliver: send failed (turn=%s): %v", turnID, err)
			}
		}
	} else {
		log.Printf("turn deliver: empty result (turn=%s)", turnID)
	}

	_, _ = tx.Exec(ctx, "UPDATE turns SET status = 'delivered', updated_at = NOW() WHERE id = $1", turnID)
	_, _ = tx.Exec(ctx, "UPDATE message_queue SET status = 'done' WHERE turn_id = $1", turnID)
	tx.Commit(ctx)
	return true
}

// failTurnLineReply 在 turn 失敗時，用最後一則訊息把該使用者的 LINE pending
// 取件按鈕轉為 error，避免使用者點按後永久等待。
func failTurnLineReply(db *pgxpool.Pool, ctx context.Context, messages []json.RawMessage) {
	if len(messages) == 0 {
		return
	}
	var last model.StandardMessage
	if err := json.Unmarshal(messages[len(messages)-1], &last); err != nil {
		return
	}
	failPendingLineReply(db, ctx, &last)
}

// stopTurnTyping 停掉 turn 內所有訊息的輸入指示器。
func stopTurnTyping(db *pgxpool.Pool, ctx context.Context, turnID string) {
	rows, err := db.Query(ctx, "SELECT id::text FROM message_queue WHERE turn_id = $1", turnID)
	if err != nil {
		return
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err == nil {
			messenger.StopTyping(id)
		}
	}
}
