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

const service = "rate-limiter"

var (
	rdb *redis.Client
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func main() {
	host := getenv("REDIS_CACHE_HOST", "redis-cache")
	port := getenv("REDIS_CACHE_PORT", "6379")

	rdb = redis.NewClient(&redis.Options{
		Addr:         host + ":" + port,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
		PoolSize:     8,
	})

	r := chi.NewRouter()

	r.Get("/healthz", func(w http.ResponseWriter, req *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok", "service": service})
	})

	r.Post("/configure", func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Key    string `json:"key"`
			Limit  int    `json:"limit"`
			Window int    `json:"window_seconds"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			writeJSON(w, 400, map[string]string{"error": "invalid body"})
			return
		}
		if body.Key == "" || body.Limit <= 0 {
			writeJSON(w, 400, map[string]string{"error": "key and positive limit required"})
			return
		}
		if body.Window <= 0 {
			body.Window = 60
		}
		ctx, cancel := context.WithTimeout(req.Context(), 2*time.Second)
		defer cancel()
		if err := rdb.HSet(ctx, "rl_cfg:"+body.Key, map[string]any{
			"limit":  body.Limit,
			"window": body.Window,
		}).Err(); err != nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		writeJSON(w, 200, map[string]any{"key": body.Key, "limit": body.Limit, "window_seconds": body.Window})
	})

	r.Post("/check", func(w http.ResponseWriter, req *http.Request) {
		var body struct {
			Key string `json:"key"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Key == "" {
			writeJSON(w, 400, map[string]string{"error": "key required"})
			return
		}
		ctx, cancel := context.WithTimeout(req.Context(), 2*time.Second)
		defer cancel()

		cfg, err := rdb.HGetAll(ctx, "rl_cfg:"+body.Key).Result()
		if err != nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		limit := 60
		windowSec := 60
		if v, ok := cfg["limit"]; ok {
			if n, e := strconv.Atoi(v); e == nil && n > 0 {
				limit = n
			}
		}
		if v, ok := cfg["window"]; ok {
			if n, e := strconv.Atoi(v); e == nil && n > 0 {
				windowSec = n
			}
		}
		bucket := time.Now().Unix() / int64(windowSec)
		counterKey := "rl:" + body.Key + ":" + strconv.FormatInt(bucket, 10)

		count, err := rdb.Incr(ctx, counterKey).Result()
		if err != nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		if count == 1 {
			if err := rdb.Expire(ctx, counterKey, time.Duration(windowSec)*time.Second).Err(); err != nil {
				log.Printf("ERROR rate-limiter: %v", err)
			}
		}
		remaining := limit - int(count)
		if remaining < 0 {
			remaining = 0
		}
		allowed := int(count) <= limit
		status := 200
		if !allowed {
			status = 429
		}
		writeJSON(w, status, map[string]any{
			"key": body.Key, "allowed": allowed, "count": count, "limit": limit,
			"remaining": remaining, "window_seconds": windowSec,
		})
	})

	r.Get("/usage/{key}", func(w http.ResponseWriter, req *http.Request) {
		key := chi.URLParam(req, "key")
		ctx, cancel := context.WithTimeout(req.Context(), 2*time.Second)
		defer cancel()

		cfg, err := rdb.HGetAll(ctx, "rl_cfg:"+key).Result()
		if err != nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		limit := 60
		windowSec := 60
		if v, ok := cfg["limit"]; ok {
			if n, e := strconv.Atoi(v); e == nil && n > 0 {
				limit = n
			}
		}
		if v, ok := cfg["window"]; ok {
			if n, e := strconv.Atoi(v); e == nil && n > 0 {
				windowSec = n
			}
		}
		bucket := time.Now().Unix() / int64(windowSec)
		counterKey := "rl:" + key + ":" + strconv.FormatInt(bucket, 10)
		v, err := rdb.Get(ctx, counterKey).Result()
		if err != nil && err != redis.Nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		count := 0
		if v != "" {
			if n, e := strconv.Atoi(v); e == nil {
				count = n
			}
		}
		writeJSON(w, 200, map[string]any{
			"key": key, "count": count, "limit": limit, "window_seconds": windowSec,
		})
	})

	r.Delete("/limit/{key}", func(w http.ResponseWriter, req *http.Request) {
		key := chi.URLParam(req, "key")
		ctx, cancel := context.WithTimeout(req.Context(), 2*time.Second)
		defer cancel()

		if err := rdb.Del(ctx, "rl_cfg:"+key).Err(); err != nil {
			log.Printf("ERROR rate-limiter: %v", err)
			writeJSON(w, 502, map[string]string{"error": "redis"})
			return
		}
		var cursor uint64
		deleted := 0
		for {
			keys, next, err := rdb.Scan(ctx, cursor, "rl:"+key+":*", 100).Result()
			if err != nil {
				log.Printf("ERROR rate-limiter: %v", err)
				break
			}
			if len(keys) > 0 {
				n, err := rdb.Del(ctx, keys...).Result()
				if err != nil {
					log.Printf("ERROR rate-limiter: %v", err)
				} else {
					deleted += int(n)
				}
			}
			if next == 0 {
				break
			}
			cursor = next
		}
		writeJSON(w, 200, map[string]any{"key": key, "deleted_counters": deleted})
	})

	addr := ":8080"
	log.Printf("%s listening on %s", service, addr)
	if err := http.ListenAndServe(addr, r); err != nil {
		log.Fatalf("ERROR rate-limiter: %v", err)
	}
}

func getenv(k, def string) string {
	v := os.Getenv(k)
	if v == "" {
		return def
	}
	return v
}
