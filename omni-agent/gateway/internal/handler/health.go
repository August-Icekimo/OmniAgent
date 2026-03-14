package handler

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
)

type HealthHandler struct {
	db *sql.DB
}

func NewHealthHandler(db *sql.DB) *HealthHandler {
	return &HealthHandler{db: db}
}

type HealthResponse struct {
	Status     string `json:"status,omitempty"`
	QueueDepth int    `json:"queue_depth,omitempty"`
	DBError    string `json:"db,omitempty"`
}

func (h *HealthHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "application/json")

	// Check DB connection basic health
	if err := h.db.PingContext(context.Background()); err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(HealthResponse{DBError: "unreachable"})
		return
	}

	// Get Queue Depth
	var depth int
	err := h.db.QueryRowContext(context.Background(), "SELECT count(*) FROM message_queue WHERE status = 'pending'").Scan(&depth)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		json.NewEncoder(w).Encode(HealthResponse{DBError: "query_failed"})
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(HealthResponse{
		Status:     "ok",
		QueueDepth: depth,
	})
}
