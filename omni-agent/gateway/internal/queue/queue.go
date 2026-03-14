package queue

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"omni-agent/gateway/internal/model"
)

type QueueMessage struct {
	ID       uuid.UUID
	Payload  model.StandardMessage
	Priority int
	Status   string
}

type Repository struct {
	db *sql.DB
}

func NewRepository(db *sql.DB) *Repository {
	return &Repository{db: db}
}

// Enqueue inserts a new message into the message_queue.
func (r *Repository) Enqueue(ctx context.Context, msg *model.StandardMessage, priority int) error {
	payload, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("failed to marshal message payload: %w", err)
	}

	query := `
		INSERT INTO message_queue (id, payload, priority, status)
		VALUES ($1, $2, $3, 'pending')
	`
	_, err = r.db.ExecContext(ctx, query, msg.ID, payload, priority)
	if err != nil {
		return fmt.Errorf("failed to enqueue message: %w", err)
	}

	return nil
}

// Dequeue atomically retrieves and locks a pending message, returning it.
// Returns sql.ErrNoRows if nothing is available.
func (r *Repository) Dequeue(ctx context.Context) (*QueueMessage, error) {
	query := `
		UPDATE message_queue
		SET status = 'processing', locked_at = NOW()
		WHERE id = (
			SELECT id
			FROM message_queue
			WHERE status = 'pending'
			ORDER BY priority DESC, created_at ASC
			FOR UPDATE SKIP LOCKED
			LIMIT 1
		)
		RETURNING id, payload, priority, status;
	`

	var qm QueueMessage
	var payloadBytes []byte
	err := r.db.QueryRowContext(ctx, query).Scan(&qm.ID, &payloadBytes, &qm.Priority, &qm.Status)
	if err != nil {
		return nil, err
	}

	if err := json.Unmarshal(payloadBytes, &qm.Payload); err != nil {
		return nil, fmt.Errorf("failed to unmarshal payload: %w", err)
	}

	return &qm, nil
}

// UpdateStatus marks a message as done or failed.
func (r *Repository) UpdateStatus(ctx context.Context, id uuid.UUID, status string) error {
	query := `
		UPDATE message_queue
		SET status = $1, locked_at = NULL
		WHERE id = $2
	`
	_, err := r.db.ExecContext(ctx, query, status, id)
	return err
}
