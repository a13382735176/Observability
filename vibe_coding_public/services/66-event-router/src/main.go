package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync/atomic"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

var rdb *redis.Client
var publishCount int64

func main() {
	streamHost := os.Getenv("REDIS_STREAM_HOST")
	if streamHost == "" {
		streamHost = "redis-stream"
	}
	rdb = redis.NewClient(&redis.Options{
		Addr:         streamHost + ":6379",
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/route", route)
	r.Get("/stats", stats)

	log.Println("event-router listening on 8080")
	http.ListenAndServe("0.0.0.0:8080", r)
}

func healthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "event-router"})
}

func route(w http.ResponseWriter, r *http.Request) {
	var req struct {
		EventType string          `json:"event_type"`
		Payload   json.RawMessage `json:"payload"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	args := &redis.XAddArgs{
		Stream: "events:routed",
		Values: map[string]interface{}{
			"event_type": req.EventType,
			"payload":    string(req.Payload),
		},
	}
	id, err := rdb.XAdd(ctx, args).Result()
	if err != nil {
		log.Printf("event-router: stream: %v", err)
		http.Error(w, `{"error":"stream error"}`, 503)
		return
	}
	atomic.AddInt64(&publishCount, 1)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(201)
	json.NewEncoder(w).Encode(map[string]string{"id": id})
}

func stats(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]int64{"published": atomic.LoadInt64(&publishCount)})
}
