package main

import (
	"context"
	"crypto/sha1"
	"encoding/binary"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func main() {
	rdb = redis.NewClient(&redis.Options{
		Addr:        envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout: 2 * time.Second,
		ReadTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/flags", createFlag)
	r.Get("/flags/all", listAll)
	r.Get("/flags/{name}", getFlag)
	r.Post("/check", checkFlag)

	log.Printf("feature-flag-svc starting on :8080")
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR feature-flag-svc: %v", err)
		os.Exit(1)
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": "feature-flag-svc"})
}

func createFlag(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name       string `json:"name"`
		Enabled    bool   `json:"enabled"`
		RolloutPct int    `json:"rollout_pct"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" {
		http.Error(w, "name required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := rdb.HSet(ctx, "flags:"+body.Name,
		"enabled", strconv.FormatBool(body.Enabled),
		"rollout_pct", body.RolloutPct).Err(); err != nil {
		log.Printf("ERROR feature-flag-svc: HSET %s: %v", body.Name, err)
		http.Error(w, "redis error", 502)
		return
	}
	writeJSON(w, 201, body)
}

func getFlag(w http.ResponseWriter, r *http.Request) {
	name := chi.URLParam(r, "name")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	m, err := rdb.HGetAll(ctx, "flags:"+name).Result()
	if err != nil {
		log.Printf("ERROR feature-flag-svc: HGETALL %s: %v", name, err)
		http.Error(w, "redis error", 502)
		return
	}
	if len(m) == 0 {
		http.Error(w, "not found", 404)
		return
	}
	writeJSON(w, 200, map[string]any{"name": name, "enabled": m["enabled"] == "true", "rollout_pct": parseInt(m["rollout_pct"])})
}

func listAll(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	keys, err := rdb.Keys(ctx, "flags:*").Result()
	if err != nil {
		log.Printf("ERROR feature-flag-svc: KEYS: %v", err)
		http.Error(w, "redis error", 502)
		return
	}
	out := []map[string]any{}
	for _, k := range keys {
		m, err := rdb.HGetAll(ctx, k).Result()
		if err != nil {
			log.Printf("ERROR feature-flag-svc: HGETALL %s: %v", k, err)
			continue
		}
		out = append(out, map[string]any{"name": k[len("flags:"):], "enabled": m["enabled"] == "true", "rollout_pct": parseInt(m["rollout_pct"])})
	}
	writeJSON(w, 200, out)
}

func checkFlag(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Name   string `json:"name"`
		UserID string `json:"user_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" || body.UserID == "" {
		http.Error(w, "name and user_id required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	m, err := rdb.HGetAll(ctx, "flags:"+body.Name).Result()
	if err != nil {
		log.Printf("ERROR feature-flag-svc: HGETALL %s: %v", body.Name, err)
		http.Error(w, "redis error", 502)
		return
	}
	if len(m) == 0 {
		writeJSON(w, 200, map[string]any{"name": body.Name, "active": false, "reason": "missing"})
		return
	}
	if m["enabled"] != "true" {
		writeJSON(w, 200, map[string]any{"name": body.Name, "active": false, "reason": "disabled"})
		return
	}
	pct := parseInt(m["rollout_pct"])
	h := sha1.Sum([]byte(body.UserID + ":" + body.Name))
	bucket := int(binary.BigEndian.Uint32(h[:4]) % 100)
	active := bucket < pct
	writeJSON(w, 200, map[string]any{"name": body.Name, "active": active, "bucket": bucket, "rollout_pct": pct})
}

func parseInt(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
