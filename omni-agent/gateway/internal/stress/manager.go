package stress

import (
	"context"
	"database/sql"
	"encoding/json"
	"log/slog"
	"time"
)

type StressMetrics struct {
	QueueDepth        int           `json:"queue_depth"`
	QueueGrowthRate   float64       `json:"queue_growth_rate"`
	P95ProcessingTime time.Duration `json:"p95_processing_time"`
	ErrorRate         float64       `json:"error_rate"`
	ActiveUsers       int           `json:"active_users"`
}

type StressLevel string

const (
	StressCalm      StressLevel = "StressCalm"
	StressBusy      StressLevel = "StressBusy"
	StressOverload  StressLevel = "StressOverload"
	StressCritical  StressLevel = "StressCritical"
)

type Manager struct {
	db       *sql.DB
	interval time.Duration
}

func NewManager(db *sql.DB, interval time.Duration) *Manager {
	if interval == 0 {
		interval = 30 * time.Second
	}
	return &Manager{
		db:       db,
		interval: interval,
	}
}

func (m *Manager) Start(ctx context.Context) {
	ticker := time.NewTicker(m.interval)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				slog.Info("StressManager stopped")
				return
			case <-ticker.C:
				m.evaluate()
			}
		}
	}()
}

func (m *Manager) evaluate() {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	var pendingCount, failedCount, totalCount int
	
	// Simplistic metrics collection for Phase 1
	err := m.db.QueryRowContext(ctx, "SELECT count(*) FROM message_queue WHERE status = 'pending'").Scan(&pendingCount)
	if err != nil {
		slog.Error("StressManager: failed to get pending count", "error", err)
		return
	}
	
	err = m.db.QueryRowContext(ctx, "SELECT count(*) FROM message_queue WHERE status = 'failed'").Scan(&failedCount)
	if err == nil {
		_ = m.db.QueryRowContext(ctx, "SELECT count(*) FROM message_queue").Scan(&totalCount)
	}

	metrics := StressMetrics{
		QueueDepth:      pendingCount,
		QueueGrowthRate: 0.0, // Simplification for Phase 1
		ErrorRate:       0.0,
	}

	if totalCount > 0 {
		metrics.ErrorRate = float64(failedCount) / float64(totalCount)
	}

	level := StressCalm
	mood := "悠閒"

	if metrics.QueueDepth > 50 || metrics.ErrorRate > 0.5 {
		level = StressCritical
		mood = "崩潰中"
	} else if metrics.QueueDepth > 35 || metrics.ErrorRate > 0.25 {
		level = StressOverload
		mood = "太多訊息啦！"
	} else if metrics.QueueDepth > 20 || metrics.ErrorRate > 0.1 {
		level = StressBusy
		mood = "有點忙"
	}

	if level == StressCritical {
		slog.Error("CRITICAL STRESS LEVEL REACHED", "metrics", metrics)
	}

	if level == StressBusy || level == StressOverload || level == StressCritical {
		metricsJSON, _ := json.Marshal(metrics)
		_, err := m.db.ExecContext(ctx, `
			INSERT INTO stress_logs (level, metrics, mood)
			VALUES ($1, $2, $3)`, level, string(metricsJSON), mood)
		if err != nil {
			slog.Error("StressManager: failed to write stress log", "error", err)
		} else {
			slog.Warn("StressManager: Elevated stress level detected", "level", level, "queue_depth", metrics.QueueDepth)
		}
	}
}
