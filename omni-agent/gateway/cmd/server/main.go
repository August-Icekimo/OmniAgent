package main

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	_ "github.com/lib/pq"

	"omni-agent/gateway/internal/forwarder"
	"omni-agent/gateway/internal/handler"
	"omni-agent/gateway/internal/queue"
	"omni-agent/gateway/internal/stress"
)

func main() {
	// 1. Structured Logging Setup
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelDebug,
	}))
	slog.SetDefault(logger)
	slog.Info("Starting Omni-Agent Gateway...")

	// 2. Database Connection
	host := getEnvOrDefault("POSTGRES_HOST", "postgres")
	port := getEnvOrDefault("POSTGRES_PORT", "5432")
	user := getEnvOrDefault("POSTGRES_USER", "omni")
	pass := getEnvOrDefault("POSTGRES_PASSWORD", "changeme")
	dbname := getEnvOrDefault("POSTGRES_DB", "omni_agent")

	dsn := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable", 
		host, port, user, pass, dbname)

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		slog.Error("Failed to open db", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	// Wait up to 30s for DB to be available during startup
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	
	for {
		err = db.PingContext(ctx)
		if err == nil {
			break
		}
		if ctx.Err() != nil {
			slog.Error("Database unreachable, terminating...", "error", err)
			os.Exit(1)
		}
		slog.Warn("DB not ready, retrying in 1s...", "error", err)
		time.Sleep(1 * time.Second)
	}
	slog.Info("PostgreSQL connected successfully")

	// 3. Components Initialization
	repo := queue.NewRepository(db)
	
	lineHandler := handler.NewLineHandler(repo)
	bbHandler := handler.NewBlueBubblesHandler(repo)
	healthHandler := handler.NewHealthHandler(db)

	stressManager := stress.NewManager(db, 30*time.Second)
	brainForwarder := forwarder.NewBrainForwarder(repo)

	// 4. Background Services
	sysCtx, sysCancel := context.WithCancel(context.Background())
	defer sysCancel()

	stressManager.Start(sysCtx)
	if brainForwarder != nil {
		brainForwarder.Start(sysCtx)
	}

	// 5. Router and Server
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))
	// Log request middleware simplified for JSON structure could go here if needed

	r.Get("/health", healthHandler.ServeHTTP)
	r.Post("/webhook/line", lineHandler.ServeHTTP)
	r.Post("/webhook/bluebubbles", bbHandler.ServeHTTP)

	portEnv := getEnvOrDefault("GATEWAY_PORT", "8080")
	server := &http.Server{
		Addr:    ":" + portEnv,
		Handler: r,
	}

	// Execute Server
	go func() {
		slog.Info("HTTP server running", "port", portEnv)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("HTTP server failed", "error", err)
			os.Exit(1)
		}
	}()

	// 6. Graceful Shutdown Wait
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	slog.Info("Shutting down Gateway gracefully...")
	sysCancel()

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := server.Shutdown(shutdownCtx); err != nil {
		slog.Error("Server forced to shutdown", "error", err)
	}

	slog.Info("Gateway exited")
}

func getEnvOrDefault(key, fallback string) string {
	if val, ok := os.LookupEnv(key); ok && val != "" {
		return val
	}
	return fallback
}
