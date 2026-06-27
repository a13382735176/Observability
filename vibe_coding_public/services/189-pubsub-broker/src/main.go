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
	"github.com/redis/go-redis/v9"
)

const SERVICE = "pubsub-broker"

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
	r.Post("/publish", publish)
	r.Post("/subscribe", subscribe)
	r.Delete("/subscribe", unsubscribe)
	r.Get("/messages/{topic}", listMessages)
	r.Get("/subscribers/{topic}", listSubscribers)
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

func publish(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Topic   string `json:"topic"`
		Payload string `json:"payload"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Topic == "" {
		http.Error(w, "topic and payload required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	streamKey := "stream:" + body.Topic
	id, err := stream.XAdd(ctx, &redis.XAddArgs{
		Stream: streamKey,
		Values: map[string]any{
			"payload": body.Payload,
			"ts":      time.Now().UTC().Format(time.RFC3339),
		},
	}).Result()
	if err != nil {
		log.Printf("ERROR %s: XADD %s: %v", SERVICE, streamKey, err)
		http.Error(w, "stream error", 502)
		return
	}

	cctx, ccancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer ccancel()
	count, cerr := cache.Incr(cctx, "pubcount:"+body.Topic).Result()
	if cerr != nil {
		log.Printf("ERROR %s: INCR pubcount:%s: %v", SERVICE, body.Topic, cerr)
	}

	writeJSON(w, 200, map[string]any{
		"topic":   body.Topic,
		"id":      id,
		"count":   count,
		"payload": body.Payload,
	})
}

func subscribe(w http.ResponseWriter, r *http.Request) {
	var body struct {
		SubscriberID string `json:"subscriber_id"`
		Topic        string `json:"topic"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.SubscriberID == "" || body.Topic == "" {
		http.Error(w, "subscriber_id and topic required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	if _, err := cache.SAdd(ctx, "subs:"+body.Topic, body.SubscriberID).Result(); err != nil {
		log.Printf("ERROR %s: SADD subs:%s: %v", SERVICE, body.Topic, err)
		http.Error(w, "cache error", 502)
		return
	}
	if _, err := cache.SAdd(ctx, "topics:"+body.SubscriberID, body.Topic).Result(); err != nil {
		log.Printf("ERROR %s: SADD topics:%s: %v", SERVICE, body.SubscriberID, err)
		http.Error(w, "cache error", 502)
		return
	}

	writeJSON(w, 200, map[string]any{
		"subscriber_id": body.SubscriberID,
		"topic":         body.Topic,
		"subscribed":    true,
	})
}

func unsubscribe(w http.ResponseWriter, r *http.Request) {
	var body struct {
		SubscriberID string `json:"subscriber_id"`
		Topic        string `json:"topic"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.SubscriberID == "" || body.Topic == "" {
		http.Error(w, "subscriber_id and topic required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	if _, err := cache.SRem(ctx, "subs:"+body.Topic, body.SubscriberID).Result(); err != nil {
		log.Printf("ERROR %s: SREM subs:%s: %v", SERVICE, body.Topic, err)
		http.Error(w, "cache error", 502)
		return
	}
	if _, err := cache.SRem(ctx, "topics:"+body.SubscriberID, body.Topic).Result(); err != nil {
		log.Printf("ERROR %s: SREM topics:%s: %v", SERVICE, body.SubscriberID, err)
		http.Error(w, "cache error", 502)
		return
	}

	writeJSON(w, 200, map[string]any{
		"subscriber_id": body.SubscriberID,
		"topic":         body.Topic,
		"subscribed":    false,
	})
}

func listMessages(w http.ResponseWriter, r *http.Request) {
	topic := chi.URLParam(r, "topic")
	count := int64(20)
	if c := r.URL.Query().Get("count"); c != "" {
		if n, err := strconv.ParseInt(c, 10, 64); err == nil && n > 0 && n <= 200 {
			count = n
		}
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	streamKey := "stream:" + topic
	msgs, err := stream.XRevRangeN(ctx, streamKey, "+", "-", count).Result()
	if err != nil {
		log.Printf("ERROR %s: XREVRANGE %s: %v", SERVICE, streamKey, err)
		http.Error(w, "stream error", 502)
		return
	}
	out := make([]map[string]any, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, map[string]any{"id": m.ID, "values": m.Values})
	}
	writeJSON(w, 200, map[string]any{"topic": topic, "messages": out})
}

func listSubscribers(w http.ResponseWriter, r *http.Request) {
	topic := chi.URLParam(r, "topic")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	members, err := cache.SMembers(ctx, "subs:"+topic).Result()
	if err != nil {
		log.Printf("ERROR %s: SMEMBERS subs:%s: %v", SERVICE, topic, err)
		http.Error(w, "cache error", 502)
		return
	}
	writeJSON(w, 200, map[string]any{"topic": topic, "subscribers": members})
}

func stats(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	out := map[string]int64{}
	var cursor uint64
	for {
		keys, next, err := cache.Scan(ctx, cursor, "pubcount:*", 100).Result()
		if err != nil {
			log.Printf("ERROR %s: SCAN pubcount:*: %v", SERVICE, err)
			http.Error(w, "cache error", 502)
			return
		}
		for _, k := range keys {
			v, gerr := cache.Get(ctx, k).Result()
			if gerr != nil {
				log.Printf("ERROR %s: GET %s: %v", SERVICE, k, gerr)
				continue
			}
			n, perr := strconv.ParseInt(v, 10, 64)
			if perr != nil {
				continue
			}
			topic := strings.TrimPrefix(k, "pubcount:")
			out[topic] = n
		}
		if next == 0 {
			break
		}
		cursor = next
	}
	writeJSON(w, 200, out)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
