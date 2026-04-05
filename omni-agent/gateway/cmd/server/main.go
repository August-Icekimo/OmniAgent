package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"omni-agent/gateway/internal/forwarder"
	"omni-agent/gateway/internal/handler"
	"omni-agent/gateway/internal/stress"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/joho/godotenv"
)

func main() {
	_ = godotenv.Load() // ignore error, as .env might not exist in docker container, we use env vars directly

	fmt.Println("Starting Omni-Agent Gateway...")

	dbUrl := fmt.Sprintf("postgres://%s:%s@%s:%s/%s",
		os.Getenv("POSTGRES_USER"),
		os.Getenv("POSTGRES_PASSWORD"),
		os.Getenv("POSTGRES_HOST"),
		os.Getenv("POSTGRES_PORT"),
		os.Getenv("POSTGRES_DB"),
	)

	var db *pgxpool.Pool
	var err error
	// Retry loop for DB connection as required by TC-01-C
	for {
		db, err = pgxpool.New(context.Background(), dbUrl)
		if err == nil {
			err = db.Ping(context.Background())
		}
		if err == nil {
			fmt.Println("PostgreSQL connected successfully")
			break
		}
		fmt.Println("DB not ready, retrying in 1s...")
		time.Sleep(1 * time.Second)
	}
	defer db.Close()

	// Start Background Worker
	stress.StartStressManager(db)
	forwarder.StartBrainForwarder(db)

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	
	// Custom logger that outputs valid JSON and doesn't log message body or webhook body
	r.Use(gin.LoggerWithFormatter(func(param gin.LogFormatterParams) string {
		return fmt.Sprintf("{\"method\":\"%s\",\"path\":\"%s\",\"status\":%d,\"latency\":\"%s\"}\n",
			param.Method, param.Path, param.StatusCode, param.Latency)
	}))
	r.Use(gin.Recovery())

	// Health check endpoint
	r.GET("/health", func(c *gin.Context) {
		var depth int
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		
		err := db.QueryRow(ctx, "SELECT COUNT(*) FROM message_queue WHERE status = 'pending'").Scan(&depth)
		if err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"status": "error",
				"db":     "down",
			})
			return
		}
		c.JSON(http.StatusOK, gin.H{
			"status":      "ok",
			"queue_depth": depth,
		})
	})

	r.POST("/webhook/line", handler.LineWebhook(db))
	r.POST("/webhook/bluebubbles", handler.BlueBubblesWebhook(db))

	tgToken := os.Getenv("TELEGRAM_BOT_TOKEN")
	if tgToken == "" {
		log.Println("TELEGRAM_BOT_TOKEN not set, Telegram webhook disabled")
		r.POST("/webhook/telegram", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Telegram webhook disabled"})
		})
	} else {
		log.Println("Telegram webhook handler registered")
		r.POST("/webhook/telegram", handler.TelegramWebhook(db))
	}


	port := os.Getenv("GATEWAY_PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("Gateway listening on :%s\n", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
