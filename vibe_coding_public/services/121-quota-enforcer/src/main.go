package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

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

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]string{"status": "ok", "service": "quota-enforcer"})
}

func setLimit(w http.ResponseWriter, r *http.Request) {
	apiKey := chi.URLParam(r, "api_key")
	var body struct {
		LimitPerHour int `json:"limit_per_hour"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.LimitPerHour <= 0 {
		writeJSON(w, 400, map[string]string{"error": "limit_per_hour must be positive int"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := cache.HSet(ctx, "qlimit:"+apiKey, "limit_per_hour", body.LimitPerHour).Err(); err != nil {
		log.Printf("ERROR quota-enforcer: hset limit: %v", err)
		writeJSON(w, 502, map[string]string{"error": "cache error"})
		return
	}
	writeJSON(w, 201, map[string]any{"api_key": apiKey, "limit_per_hour": body.LimitPerHour})
}

func getLimit(w http.ResponseWriter, r *http.Request) {
	apiKey := chi.URLParam(r, "api_key")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	m, err := cache.HGetAll(ctx, "qlimit:"+apiKey).Result()
	if err != nil {
		log.Printf("ERROR quota-enforcer: hgetall: %v", err)
		writeJSON(w, 502, map[string]string{"error": "cache error"})
		return
	}
	if len(m) == 0 {
		writeJSON(w, 404, map[string]string{"error": "not found"})
		return
	}
	writeJSON(w, 200, m)
}

func check(w http.ResponseWriter, r *http.Request) {
	var body struct {
		APIKey   string `json:"api_key"`
		Resource string `json:"resource"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.APIKey == "" || body.Resource == "" {
		writeJSON(w, 400, map[string]string{"error": "api_key and resource required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	lim, err := cache.HGet(ctx, "qlimit:"+body.APIKey, "limit_per_hour").Int64()
	if err == redis.Nil {
		writeJSON(w, 404, map[string]string{"error": "no quota configured"})
		return
	}
	if err != nil {
		log.Printf("ERROR quota-enforcer: get limit: %v", err)
		writeJSON(w, 502, map[string]string{"error": "cache error"})
		return
	}

	hour := time.Now().UTC().Format("2006010215")
	key := "quota:" + body.APIKey + ":" + body.Resource + ":" + hour
	cnt, err := cache.Incr(ctx, key).Result()
	if err != nil {
		log.Printf("ERROR quota-enforcer: incr: %v", err)
		writeJSON(w, 502, map[string]string{"error": "cache error"})
		return
	}
	if cnt == 1 {
		_ = cache.Expire(ctx, key, time.Hour).Err()
	}

	remaining := lim - cnt
	allowed := cnt <= lim
	if !allowed {
		sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer scancel()
		_, serr := stream.XAdd(sctx, &redis.XAddArgs{
			Stream: "events:quota_exceeded",
			MaxLen: 10000,
			Approx: true,
			Values: map[string]any{
				"api_key":  body.APIKey,
				"resource": body.Resource,
				"hour":     hour,
				"count":    strconv.FormatInt(cnt, 10),
				"limit":    strconv.FormatInt(lim, 10),
			},
		}).Result()
		if serr != nil {
			log.Printf("ERROR quota-enforcer: xadd: %v", serr)
		}
	}
	if remaining < 0 {
		remaining = 0
	}
	writeJSON(w, 200, map[string]any{
		"allowed":   allowed,
		"count":     cnt,
		"limit":     lim,
		"remaining": remaining,
	})
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
	r.Post("/quotas/{api_key}", setLimit)
	r.Get("/quotas/{api_key}", getLimit)
	r.Post("/check", check)

	log.Println("INFO quota-enforcer: listening on 0.0.0.0:8080")
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Fatalf("ERROR quota-enforcer: %v", err)
	}
}
