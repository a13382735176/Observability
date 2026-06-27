package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "match-maker"

var (
	cacheClient  *redis.Client
	streamClient *redis.Client
)

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	cacheClient = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	streamClient = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_STREAM_HOST", "redis-stream") + ":" + envOr("REDIS_STREAM_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/queue", enqueue)
	r.Get("/queue/{mode}/length", queueLength)
	r.Post("/match/accept", acceptMatch)
	r.Get("/matches/recent", recentMatches)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR %s: %v", SERVICE, err)
		os.Exit(1)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

func enqueue(w http.ResponseWriter, r *http.Request) {
	var body struct {
		UserID       string `json:"user_id"`
		SkillRating  int64  `json:"skill_rating"`
		Mode         string `json:"mode"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.UserID == "" || body.Mode == "" {
		http.Error(w, "user_id and mode required", 400)
		return
	}

	queueKey := "mm:" + body.Mode
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	payload, _ := json.Marshal(map[string]any{
		"user_id":      body.UserID,
		"skill_rating": body.SkillRating,
		"enqueued_at":  time.Now().UTC().Format(time.RFC3339),
	})
	if err := cacheClient.RPush(ctx, queueKey, string(payload)).Err(); err != nil {
		log.Printf("ERROR %s: RPUSH %s: %v", SERVICE, queueKey, err)
		http.Error(w, "cache error", 502)
		return
	}

	length, err := cacheClient.LLen(ctx, queueKey).Result()
	if err != nil {
		log.Printf("ERROR %s: LLEN %s: %v", SERVICE, queueKey, err)
		http.Error(w, "cache error", 502)
		return
	}

	matched := false
	var matchID string
	if length >= 2 {
		p1, e1 := cacheClient.LPop(ctx, queueKey).Result()
		p2, e2 := cacheClient.LPop(ctx, queueKey).Result()
		if e1 == nil && e2 == nil {
			matchID = "m-" + body.Mode + "-" + time.Now().UTC().Format("20060102T150405.000")
			sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
			defer scancel()
			if _, xerr := streamClient.XAdd(sctx, &redis.XAddArgs{
				Stream: "events:matches",
				Values: map[string]any{
					"match_id": matchID,
					"mode":     body.Mode,
					"p1":       p1,
					"p2":       p2,
					"ts":       time.Now().UTC().Format(time.RFC3339),
				},
			}).Result(); xerr != nil {
				log.Printf("ERROR %s: XADD events:matches: %v", SERVICE, xerr)
				http.Error(w, "stream error", 502)
				return
			}
			matched = true
		}
	}

	writeJSON(w, 200, map[string]any{
		"mode":     body.Mode,
		"length":   length,
		"matched":  matched,
		"match_id": matchID,
	})
}

func queueLength(w http.ResponseWriter, r *http.Request) {
	mode := chi.URLParam(r, "mode")
	queueKey := "mm:" + mode
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	n, err := cacheClient.LLen(ctx, queueKey).Result()
	if err != nil {
		log.Printf("ERROR %s: LLEN %s: %v", SERVICE, queueKey, err)
		http.Error(w, "cache error", 502)
		return
	}
	writeJSON(w, 200, map[string]any{"mode": mode, "length": n})
}

func acceptMatch(w http.ResponseWriter, r *http.Request) {
	var body struct {
		MatchID string `json:"match_id"`
		UserID  string `json:"user_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.MatchID == "" || body.UserID == "" {
		http.Error(w, "match_id and user_id required", 400)
		return
	}
	setKey := "accepted:" + body.MatchID
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := cacheClient.SAdd(ctx, setKey, body.UserID).Err(); err != nil {
		log.Printf("ERROR %s: SADD %s: %v", SERVICE, setKey, err)
		http.Error(w, "cache error", 502)
		return
	}
	count, err := cacheClient.SCard(ctx, setKey).Result()
	if err != nil {
		log.Printf("ERROR %s: SCARD %s: %v", SERVICE, setKey, err)
		http.Error(w, "cache error", 502)
		return
	}

	ready := false
	if count == 2 {
		sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer scancel()
		if _, xerr := streamClient.XAdd(sctx, &redis.XAddArgs{
			Stream: "events:match_ready",
			Values: map[string]any{
				"match_id": body.MatchID,
				"ts":       time.Now().UTC().Format(time.RFC3339),
			},
		}).Result(); xerr != nil {
			log.Printf("ERROR %s: XADD events:match_ready: %v", SERVICE, xerr)
			http.Error(w, "stream error", 502)
			return
		}
		ready = true
	}
	writeJSON(w, 200, map[string]any{
		"match_id":  body.MatchID,
		"accepted":  count,
		"ready":     ready,
	})
}

func recentMatches(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	msgs, err := streamClient.XRevRangeN(ctx, "events:matches", "+", "-", 20).Result()
	if err != nil {
		log.Printf("ERROR %s: XREVRANGE events:matches: %v", SERVICE, err)
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
