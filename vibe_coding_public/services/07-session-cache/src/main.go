// 07-session-cache — session token cache backed by Redis SETEX.
//
// Endpoints:
//
//	GET /healthz
//	POST /session                 body: {"user_id": "..."} -> {"token": "...", "ttl_s": 3600}
//	GET /session/{token}          -> {"user_id": "...", "ttl_s": ...}
//	DELETE /session/{token}
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

var rdb *redis.Client

const ttlSeconds = 3600

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func newToken() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]bool{"ok": true})
}

type createReq struct {
	UserID string `json:"user_id"`
}

func handleSessionRoot(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]string{"error": "POST only"})
		return
	}
	var req createReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, 400, map[string]string{"error": "bad json: " + err.Error()})
		return
	}
	if req.UserID == "" {
		writeJSON(w, 400, map[string]string{"error": "user_id required"})
		return
	}
	tok := newToken()
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	_, err := rdb.SetEx(ctx, "sess:"+tok, req.UserID, ttlSeconds*time.Second).Result()
	if err != nil {
		log.Printf("ERROR redis setex sess:%s: %v", tok, err)
		writeJSON(w, 502, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, 200, map[string]any{"token": tok, "ttl_s": ttlSeconds})
}

func handleSessionToken(w http.ResponseWriter, r *http.Request) {
	tok := strings.TrimPrefix(r.URL.Path, "/session/")
	if tok == "" || strings.Contains(tok, "/") {
		writeJSON(w, 400, map[string]string{"error": "bad token"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	key := "sess:" + tok
	switch r.Method {
	case http.MethodGet:
		uid, err := rdb.Get(ctx, key).Result()
		if err == redis.Nil {
			writeJSON(w, 404, map[string]string{"error": "no such session"})
			return
		}
		if err != nil {
			log.Printf("ERROR redis get sess:%s: %v", tok, err)
			writeJSON(w, 502, map[string]string{"error": err.Error()})
			return
		}
		ttl, _ := rdb.TTL(ctx, key).Result()
		writeJSON(w, 200, map[string]any{"user_id": uid, "ttl_s": int(ttl.Seconds())})
	case http.MethodDelete:
		if _, err := rdb.Del(ctx, key).Result(); err != nil {
			log.Printf("ERROR redis del sess:%s: %v", tok, err)
			writeJSON(w, 502, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})
	default:
		writeJSON(w, 405, map[string]string{"error": "method not allowed"})
	}
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("session-cache starting")
	rdb = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  1 * time.Second,
		ReadTimeout:  1 * time.Second,
		WriteTimeout: 1 * time.Second,
	})
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/session", handleSessionRoot)
	mux.HandleFunc("/session/", handleSessionToken)
	log.Println("listening on :8080")
	srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("FATAL listen: %v", err)
	}
}
