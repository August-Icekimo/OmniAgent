package handler

import (
	"errors"
	"fmt"
	"os"
	"time"
)

// HandleCockpit interacts with the Cockpit API (mocked for Phase 4 but with Auth setup).
func HandleCockpit(params map[string]interface{}) (interface{}, error) {
	action, ok := params["action"].(string)
	if !ok {
		return nil, errors.New("action is required (status or restart_service)")
	}

	cockpitURL := os.Getenv("COCKPIT_URL")
	if cockpitURL == "" {
		return nil, errors.New("COCKPIT_URL not configured")
	}

	user := os.Getenv("COCKPIT_USER")
	pass := os.Getenv("COCKPIT_PASSWORD")

	if user == "" || pass == "" {
		return nil, errors.New("COCKPIT_USER or COCKPIT_PASSWORD not configured")
	}

	// For Phase 4, we simulate the Cockpit API calls.
	// A real implementation would use the provided credentials for Basic Auth.

	switch action {
	case "status":
		return map[string]interface{}{
			"cpu_usage":  "12%",
			"ram_usage":  "5.8GB / 16GB",
			"disk_usage": "210GB / 500GB",
			"status":     "active",
			"host":       cockpitURL,
			"auth":       "basic", // confirming auth config is detected
		}, nil

	case "restart_service":
		service, ok := params["service"].(string)
		if !ok {
			return nil, errors.New("service name is required for restart_service")
		}
		return map[string]interface{}{
			"service":   service,
			"action":    "restart",
			"status":    "executed",
			"timestamp": time.Now().Format(time.RFC3339),
		}, nil

	default:
		return nil, fmt.Errorf("unknown cockpit action: %s", action)
	}
}
