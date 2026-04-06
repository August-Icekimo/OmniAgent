package main

import (
	"encoding/json"
	"log"
	"net/http"
	"omni-agent/skills/handler"
	"os"
)

type SkillRequest struct {
	Skill  string                 `json:"skill"`
	Params map[string]interface{} `json:"params"`
}

type SkillResponse struct {
	Status string      `json:"status"`
	Result interface{} `json:"result,omitempty"`
	Error  string      `json:"error,omitempty"`
}

func main() {
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "skills"})
	})

	http.HandleFunc("/skills", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]map[string]string{
			{"name": "wake_on_lan", "status": "active"},
			{"name": "cockpit", "status": "active"},
			{"name": "home_assistant", "status": "stub"},
		})
	})

	http.HandleFunc("/skill/execute", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req SkillRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON", http.StatusBadRequest)
			return
		}

		var result interface{}
		var err error

		switch req.Skill {
		case "wake_on_lan":
			result, err = handler.HandleWOL(req.Params)
		case "cockpit":
			result, err = handler.HandleCockpit(req.Params)
		case "home_assistant":
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusNotImplemented)
			json.NewEncoder(w).Encode(SkillResponse{Status: "error", Error: "not implemented", Result: "home_assistant"})
			return
		default:
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusNotFound)
			json.NewEncoder(w).Encode(SkillResponse{Status: "error", Error: "skill not found"})
			return
		}

		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			json.NewEncoder(w).Encode(SkillResponse{Status: "error", Error: err.Error()})
		} else {
			json.NewEncoder(w).Encode(SkillResponse{Status: "ok", Result: result})
		}
	})

	port := os.Getenv("SKILLS_PORT")
	if port == "" {
		port = "8001"
	}
	log.Printf("Skills Server listening on :%s\n", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}
