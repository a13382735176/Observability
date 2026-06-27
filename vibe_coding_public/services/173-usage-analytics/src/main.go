package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "usage-analytics"

var (
	pg    *pgxpool.Pool
	cache *redis.Client
)

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	pgDSN := envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
	cfg, err := pgxpool.ParseConfig(pgDSN)
	if err != nil {
		log.Printf("ERROR %s: parse pg dsn: %v", SERVICE, err)
		os.Exit(1)
	}
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	cfg.MaxConns = 8

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	pg, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Printf("ERROR %s: pg connect: %v", SERVICE, err)
		os.Exit(1)
	}

	cache = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	initCtx, initCancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer initCancel()
	for _, stmt := range []string{
		`CREATE TABLE IF NOT EXISTS usage_events (
            id bigserial PRIMARY KEY,
            user_id text,
            event_type text,
            properties jsonb DEFAULT '{}'::jsonb,
            ts timestamptz DEFAULT now()
        )`,
		`CREATE INDEX IF NOT EXISTS usage_events_user_ts_idx       ON usage_events(user_id, ts DESC)`,
		`CREATE INDEX IF NOT EXISTS usage_events_event_type_ts_idx ON usage_events(event_type, ts DESC)`,
	} {
		if _, err := pg.Exec(initCtx, stmt); err != nil {
			log.Printf("ERROR %s: schema init: %v", SERVICE, err)
		}
	}

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/events", postEvent)
	r.Get("/events/user/{user_id}", eventsByUser)
	r.Get("/events/type/{event_type}/recent", eventsByType)
	r.Get("/counts/{user_id}", countsByUser)
	r.Get("/stats", stats)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR %s: %v", SERVICE, err)
		os.Exit(1)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

func postEvent(w http.ResponseWriter, r *http.Request) {
	var body struct {
		UserID     string          `json:"user_id"`
		EventType  string          `json:"event_type"`
		Properties json.RawMessage `json:"properties"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.UserID == "" || body.EventType == "" {
		http.Error(w, "user_id, event_type required", 400)
		return
	}
	if len(body.Properties) == 0 {
		body.Properties = json.RawMessage(`{}`)
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	var id int64
	var ts time.Time
	if err := pg.QueryRow(ctx,
		`INSERT INTO usage_events(user_id, event_type, properties)
		 VALUES($1,$2,$3) RETURNING id, ts`,
		body.UserID, body.EventType, []byte(body.Properties),
	).Scan(&id, &ts); err != nil {
		log.Printf("ERROR %s: insert: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}

	key := "ucount:" + body.UserID + ":" + body.EventType
	cctx, ccancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer ccancel()
	if _, err := cache.Incr(cctx, key).Result(); err != nil {
		log.Printf("ERROR %s: INCR %s: %v", SERVICE, key, err)
	} else {
		if _, err := cache.Expire(cctx, key, 24*time.Hour).Result(); err != nil {
			log.Printf("ERROR %s: EXPIRE %s: %v", SERVICE, key, err)
		}
	}

	writeJSON(w, 200, map[string]any{
		"id":         id,
		"user_id":    body.UserID,
		"event_type": body.EventType,
		"ts":         ts,
	})
}

func eventsByUser(w http.ResponseWriter, r *http.Request) {
	userID := chi.URLParam(r, "user_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := pg.Query(ctx,
		`SELECT id, user_id, event_type, properties, ts
		 FROM usage_events WHERE user_id=$1 ORDER BY id DESC LIMIT 100`, userID)
	if err != nil {
		log.Printf("ERROR %s: select user: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}
	defer rows.Close()

	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var uid, et string
		var props []byte
		var ts time.Time
		if err := rows.Scan(&id, &uid, &et, &props, &ts); err != nil {
			log.Printf("ERROR %s: scan: %v", SERVICE, err)
			continue
		}
		var p any
		if err := json.Unmarshal(props, &p); err != nil {
			p = map[string]any{}
		}
		out = append(out, map[string]any{
			"id":         id,
			"user_id":    uid,
			"event_type": et,
			"properties": p,
			"ts":         ts,
		})
	}
	writeJSON(w, 200, out)
}

func eventsByType(w http.ResponseWriter, r *http.Request) {
	eventType := chi.URLParam(r, "event_type")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := pg.Query(ctx,
		`SELECT id, user_id, event_type, properties, ts
		 FROM usage_events WHERE event_type=$1 ORDER BY id DESC LIMIT 100`, eventType)
	if err != nil {
		log.Printf("ERROR %s: select type: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}
	defer rows.Close()

	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var uid, et string
		var props []byte
		var ts time.Time
		if err := rows.Scan(&id, &uid, &et, &props, &ts); err != nil {
			log.Printf("ERROR %s: scan: %v", SERVICE, err)
			continue
		}
		var p any
		if err := json.Unmarshal(props, &p); err != nil {
			p = map[string]any{}
		}
		out = append(out, map[string]any{
			"id":         id,
			"user_id":    uid,
			"event_type": et,
			"properties": p,
			"ts":         ts,
		})
	}
	writeJSON(w, 200, out)
}

func countsByUser(w http.ResponseWriter, r *http.Request) {
	userID := chi.URLParam(r, "user_id")
	pattern := "ucount:" + userID + ":*"

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	counts := map[string]int64{}
	var cursor uint64
	for {
		keys, next, err := cache.Scan(ctx, cursor, pattern, 100).Result()
		if err != nil {
			log.Printf("ERROR %s: SCAN %s: %v", SERVICE, pattern, err)
			http.Error(w, "cache error", 502)
			return
		}
		for _, k := range keys {
			v, err := cache.Get(ctx, k).Result()
			if err != nil {
				log.Printf("ERROR %s: GET %s: %v", SERVICE, k, err)
				continue
			}
			n, err := strconv.ParseInt(v, 10, 64)
			if err != nil {
				continue
			}
			et := k[len("ucount:"+userID+":"):]
			counts[et] = n
		}
		if next == 0 {
			break
		}
		cursor = next
	}

	writeJSON(w, 200, map[string]any{
		"user_id": userID,
		"counts":  counts,
	})
}

func stats(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := pg.Query(ctx,
		`SELECT event_type, count(*) AS n
		 FROM usage_events
		 GROUP BY event_type
		 ORDER BY n DESC
		 LIMIT 50`)
	if err != nil {
		log.Printf("ERROR %s: stats: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}
	defer rows.Close()

	out := []map[string]any{}
	for rows.Next() {
		var et string
		var n int64
		if err := rows.Scan(&et, &n); err != nil {
			log.Printf("ERROR %s: scan: %v", SERVICE, err)
			continue
		}
		out = append(out, map[string]any{
			"event_type": strings.TrimSpace(et),
			"count":      n,
		})
	}
	writeJSON(w, 200, out)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
