package stress

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func StartStressManager(db *pgxpool.Pool) {
	// Evaluates every 30 seconds as requested by test TC-05
	ticker := time.NewTicker(30 * time.Second)
	go func() {
		// evaluate immediately on start
		evaluateStress(db)
		for range ticker.C {
			evaluateStress(db)
		}
	}()
}

func evaluateStress(db *pgxpool.Pool) {
	ctx := context.Background()
	var depth int
	err := db.QueryRow(ctx, "SELECT COUNT(*) FROM message_queue WHERE status = 'pending'").Scan(&depth)
	if err != nil {
		log.Println("StressManager: failed to count pending messages:", err)
		return
	}

	var level, mood, action string
	if depth >= 50 { // >= 50 as TC-05-B inserts 55
		level = "StressCritical"
		mood = "系統快崩潰了"
		action = "啟動最高等級降級策略，延遲所有非緊急任務"
		log.Println("CRITICAL STRESS LEVEL REACHED: queue_depth =", depth)
	} else if depth >= 20 { // >= 20 as TC-05-A inserts 25
		level = "StressBusy"
		mood = "有點忙"
		action = "延遲低優先級任務"
	} else {
		log.Println("StressManager: level=StressCalm")
		return
	}

	metrics := map[string]int{"queue_depth": depth}
	metricsJSON, _ := json.Marshal(metrics)

	_, err = db.Exec(ctx, 
		"INSERT INTO stress_logs (level, mood, action_taken, metrics) VALUES ($1, $2, $3, $4)",
		level, mood, action, metricsJSON)

	if err != nil {
		log.Println("StressManager: failed to write stress_logs:", err)
	}
}
