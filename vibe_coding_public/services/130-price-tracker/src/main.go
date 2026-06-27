package main

import (
	"context"
	"encoding/json"
	"log"
	"math"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "price-tracker"

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

func main() {
	cache = redis.NewClient(&redis.Options{
		Addr:        envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout: 2 * time.Second,
		ReadTimeout: 2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	stream = redis.NewClient(&redis.Options{
		Addr:        envOr("REDIS_STREAM_HOST", "redis-stream") + ":" + envOr("REDIS_STREAM_PORT", "6379"),
		DialTimeout: 2 * time.Second,
		ReadTimeout: 2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/track", trackPrice)
	r.Get("/prices/{route}", getPrice)
	r.Get("/changes", listChanges)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR %s: %v", SERVICE, err)
		os.Exit(1)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

func trackPrice(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Route             string `json:"route"`
		CurrentPriceCents int64  `json:"current_price_cents"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Route == "" {
		http.Error(w, "route and current_price_cents required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	key := "price:" + body.Route
	prev, err := cache.HGet(ctx, key, "curr").Result()
	if err != nil && err != redis.Nil {
		log.Printf("ERROR %s: HGET %s: %v", SERVICE, key, err)
		http.Error(w, "cache error", 502)
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if err := cache.HSet(ctx, key,
		"curr", strconv.FormatInt(body.CurrentPriceCents, 10),
		"prev", prev,
		"ts", now).Err(); err != nil {
		log.Printf("ERROR %s: HSET %s: %v", SERVICE, key, err)
		http.Error(w, "cache error", 502)
		return
	}

	emitted := false
	if prev != "" {
		prevN, perr := strconv.ParseInt(prev, 10, 64)
		if perr == nil && math.Abs(float64(body.CurrentPriceCents-prevN)) > 100 {
			sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
			defer scancel()
			if _, xerr := stream.XAdd(sctx, &redis.XAddArgs{
				Stream: "events:price_changes",
				Values: map[string]any{
					"route": body.Route,
					"prev":  strconv.FormatInt(prevN, 10),
					"curr":  strconv.FormatInt(body.CurrentPriceCents, 10),
					"ts":    now,
				},
			}).Result(); xerr != nil {
				log.Printf("ERROR %s: XADD events:price_changes: %v", SERVICE, xerr)
			} else {
				emitted = true
			}
		}
	}

	writeJSON(w, 200, map[string]any{
		"route":               body.Route,
		"current_price_cents": body.CurrentPriceCents,
		"prev":                prev,
		"ts":                  now,
		"emitted":             emitted,
	})
}

func getPrice(w http.ResponseWriter, r *http.Request) {
	route := chi.URLParam(r, "route")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	m, err := cache.HGetAll(ctx, "price:"+route).Result()
	if err != nil {
		log.Printf("ERROR %s: HGETALL price:%s: %v", SERVICE, route, err)
		http.Error(w, "cache error", 502)
		return
	}
	if len(m) == 0 {
		http.Error(w, "not found", 404)
		return
	}
	writeJSON(w, 200, map[string]any{"route": route, "fields": m})
}

func listChanges(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	msgs, err := stream.XRevRangeN(ctx, "events:price_changes", "+", "-", 20).Result()
	if err != nil {
		log.Printf("ERROR %s: XREVRANGE events:price_changes: %v", SERVICE, err)
		http.Error(w, "stream error", 502)
		return
	}
	out := make([]map[string]any, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, map[string]any{"id": m.ID, "values": m.Values})
	}
	writeJSON(w, 200, out)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
