package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "session-manager"
const SESSION_TTL = 86400

var (
	cache  *redis.Client
	stream *redis.Client
)

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func newSessionID() (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func main() {
	cache = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	stream = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_STREAM_HOST", "redis-stream") + ":" + envOr("REDIS_STREAM_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/sessions", createSession)
	r.Get("/sessions/{session_id}", getSession)
	r.Delete("/sessions/{session_id}", deleteSession)
	r.Get("/sessions/user/{user_id}", listUserSessions)
	r.Post("/sessions/{session_id}/refresh", refreshSession)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR %s: %v", SERVICE, err)
		os.Exit(1)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

type sessionData struct {
	UserID    string `json:"user_id"`
	IP        string `json:"ip"`
	UA        string `json:"ua"`
	CreatedAt string `json:"created_at"`
}

func createSession(w http.ResponseWriter, r *http.Request) {
	var body struct {
		UserID    string `json:"user_id"`
		IPAddress string `json:"ip_address"`
		UserAgent string `json:"user_agent"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.UserID == "" {
		http.Error(w, "user_id required", 400)
		return
	}
	sid, err := newSessionID()
	if err != nil {
		log.Printf("ERROR %s: rand: %v", SERVICE, err)
		http.Error(w, "rand error", 500)
		return
	}
	data := sessionData{
		UserID:    body.UserID,
		IP:        body.IPAddress,
		UA:        body.UserAgent,
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
	}
	js, _ := json.Marshal(data)

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := cache.Set(ctx, "sess:"+sid, js, time.Duration(SESSION_TTL)*time.Second).Err(); err != nil {
		log.Printf("ERROR %s: SET sess:%s: %v", SERVICE, sid, err)
		http.Error(w, "cache error", 502)
		return
	}
	if err := cache.SAdd(ctx, "user_sess:"+body.UserID, sid).Err(); err != nil {
		log.Printf("ERROR %s: SADD user_sess:%s: %v", SERVICE, body.UserID, err)
	}

	sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer scancel()
	if _, err := stream.XAdd(sctx, &redis.XAddArgs{
		Stream: "events:logins",
		Values: map[string]any{
			"user_id": body.UserID,
			"ip":      body.IPAddress,
			"ua":      body.UserAgent,
		},
	}).Result(); err != nil {
		log.Printf("ERROR %s: XADD events:logins: %v", SERVICE, err)
	}

	writeJSON(w, 201, map[string]any{"session_id": sid, "expires_in": SESSION_TTL})
}

func getSession(w http.ResponseWriter, r *http.Request) {
	sid := chi.URLParam(r, "session_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	v, err := cache.Get(ctx, "sess:"+sid).Result()
	if err == redis.Nil {
		writeJSON(w, 200, map[string]any{"valid": false})
		return
	}
	if err != nil {
		log.Printf("ERROR %s: GET sess:%s: %v", SERVICE, sid, err)
		http.Error(w, "cache error", 502)
		return
	}
	var d sessionData
	_ = json.Unmarshal([]byte(v), &d)
	writeJSON(w, 200, map[string]any{
		"valid":      true,
		"session_id": sid,
		"user_id":    d.UserID,
		"ip":         d.IP,
		"ua":         d.UA,
		"created_at": d.CreatedAt,
	})
}

func deleteSession(w http.ResponseWriter, r *http.Request) {
	sid := chi.URLParam(r, "session_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	v, err := cache.Get(ctx, "sess:"+sid).Result()
	userID := ""
	if err == nil {
		var d sessionData
		if jerr := json.Unmarshal([]byte(v), &d); jerr == nil {
			userID = d.UserID
		}
	} else if err != redis.Nil {
		log.Printf("ERROR %s: GET sess:%s: %v", SERVICE, sid, err)
	}

	if err := cache.Del(ctx, "sess:"+sid).Err(); err != nil {
		log.Printf("ERROR %s: DEL sess:%s: %v", SERVICE, sid, err)
		http.Error(w, "cache error", 502)
		return
	}
	if userID != "" {
		if err := cache.SRem(ctx, "user_sess:"+userID, sid).Err(); err != nil {
			log.Printf("ERROR %s: SREM user_sess:%s: %v", SERVICE, userID, err)
		}
	}

	sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer scancel()
	if _, err := stream.XAdd(sctx, &redis.XAddArgs{
		Stream: "events:logouts",
		Values: map[string]any{
			"user_id":    userID,
			"session_id": sid,
		},
	}).Result(); err != nil {
		log.Printf("ERROR %s: XADD events:logouts: %v", SERVICE, err)
	}

	writeJSON(w, 200, map[string]any{"deleted": true})
}

func listUserSessions(w http.ResponseWriter, r *http.Request) {
	uid := chi.URLParam(r, "user_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	sids, err := cache.SMembers(ctx, "user_sess:"+uid).Result()
	if err != nil {
		log.Printf("ERROR %s: SMEMBERS user_sess:%s: %v", SERVICE, uid, err)
		http.Error(w, "cache error", 502)
		return
	}
	out := make([]map[string]any, 0, len(sids))
	for _, sid := range sids {
		v, gerr := cache.Get(ctx, "sess:"+sid).Result()
		if gerr == redis.Nil {
			continue
		}
		if gerr != nil {
			log.Printf("ERROR %s: GET sess:%s: %v", SERVICE, sid, gerr)
			continue
		}
		var d sessionData
		_ = json.Unmarshal([]byte(v), &d)
		out = append(out, map[string]any{
			"session_id": sid,
			"user_id":    d.UserID,
			"ip":         d.IP,
			"ua":         d.UA,
			"created_at": d.CreatedAt,
		})
	}
	writeJSON(w, 200, out)
}

func refreshSession(w http.ResponseWriter, r *http.Request) {
	sid := chi.URLParam(r, "session_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ok, err := cache.Expire(ctx, "sess:"+sid, time.Duration(SESSION_TTL)*time.Second).Result()
	if err != nil {
		log.Printf("ERROR %s: EXPIRE sess:%s: %v", SERVICE, sid, err)
		http.Error(w, "cache error", 502)
		return
	}
	if !ok {
		writeJSON(w, 404, map[string]any{"refreshed": false})
		return
	}
	writeJSON(w, 200, map[string]any{"refreshed": true, "expires_in": SESSION_TTL})
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
