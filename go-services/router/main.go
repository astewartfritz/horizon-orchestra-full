package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/astewartfritz/horizon-orchestra/go-services/router/state"
)

func main() {
	port := os.Getenv("ROUTER_PORT")
	if port == "" {
		port = "8400"
	}

	redisURL := os.Getenv("REDIS_URL")

	var store interface {
		Create(string, string) *state.TaskState
		Get(string) (*state.TaskState, bool)
		AddStep(string, state.StepResult) bool
		Complete(string, string) bool
		Fail(string, string) bool
		List(string, int) []*state.TaskState
		Delete(string) bool
		Trace(string) []state.TraceEvent
		Subscribe() <-chan map[string]any
		Unsubscribe(<-chan map[string]any)
	}

	if redisURL != "" {
		store = state.NewRedisStore(redisURL)
		log.Printf("Using Redis-backed store: %s", redisURL)
	} else {
		store = state.NewStore()
		log.Printf("Using in-memory store")
	}

	mux := http.NewServeMux()

	// REST API
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":     "ok",
			"service":    "router-state-manager",
			"redis":      redisURL != "",
			"time":       time.Now().UTC().Format(time.RFC3339),
		})
	})

	mux.HandleFunc("POST /api/tasks", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			UserInput string `json:"user_input"`
			Intent    string `json:"intent"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
			return
		}
		s := store.Create(req.UserInput, req.Intent)
		writeJSON(w, http.StatusCreated, s)
	})

	mux.HandleFunc("GET /api/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		s, ok := store.Get(id)
		if !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		writeJSON(w, http.StatusOK, s)
	})

	mux.HandleFunc("POST /api/tasks/{id}/steps", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		var req struct {
			Step   int    `json:"step"`
			Agent  string `json:"agent"`
			Status string `json:"status"`
			Output string `json:"output"`
			Error  string `json:"error,omitempty"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
			return
		}
		result := state.StepResult{
			Step:   req.Step,
			Agent:  req.Agent,
			Status: req.Status,
			Output: req.Output,
			Error:  req.Error,
		}
		if ok := store.AddStep(id, result); !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "added"})
	})

	mux.HandleFunc("POST /api/tasks/{id}/complete", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		var req struct {
			Output string `json:"output"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
			return
		}
		if ok := store.Complete(id, req.Output); !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "completed"})
	})

	mux.HandleFunc("POST /api/tasks/{id}/fail", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		var req struct {
			Error string `json:"error"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
			return
		}
		if ok := store.Fail(id, req.Error); !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "failed"})
	})

	mux.HandleFunc("GET /api/tasks", func(w http.ResponseWriter, r *http.Request) {
		status := r.URL.Query().Get("status")
		limit := 50
		tasks := store.List(status, limit)
		writeJSON(w, http.StatusOK, map[string]any{
			"tasks": tasks,
			"count": len(tasks),
		})
	})

	mux.HandleFunc("DELETE /api/tasks/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if ok := store.Delete(id); !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "task not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
	})

	mux.HandleFunc("GET /api/tasks/{id}/trace", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		trace := store.Trace(id)
		writeJSON(w, http.StatusOK, map[string]any{
			"task_id": id,
			"trace":   trace,
		})
	})

	mux.HandleFunc("GET /api/events", func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming not supported", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")

		eventCh := store.Subscribe()
		defer store.Unsubscribe(eventCh)

		ctx := r.Context()
		for {
			select {
			case <-ctx.Done():
				return
			case event, ok := <-eventCh:
				if !ok {
					return
				}
				data, _ := json.Marshal(event)
				fmt.Fprintf(w, "data: %s\n\n", data)
				flusher.Flush()
			}
		}
	})

	// ── Scaling endpoints ──

	mux.HandleFunc("GET /api/scaling/workers", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"workers": []map[string]any{},
			"count":   0,
		})
	})

	addr := fmt.Sprintf(":%s", port)
	log.Printf("Router state manager listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}
