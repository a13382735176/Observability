package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
)

const maxMessageCount = 200

type app struct {
	name        string
	cacheRedis  *redis.Client
	streamRedis *redis.Client
}

type publishRequest struct {
	Topic   string      `json:"topic"`
	Payload interface{} `json:"payload"`
}

type subscriptionRequest struct {
	SubscriberID string `json:"subscriber_id"`
	Topic        string `json:"topic"`
}

type streamMessage struct {
	ID     string                 `json:"id"`
	Values map[string]interface{} `json:"values"`
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (w *responseWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}

func main() {
	name := getenv("APP_NAME", "pubsub-broker-skill")
	a := &app{
		name:        name,
		cacheRedis:  newRedisClient("REDIS_CACHE_HOST", "REDIS_CACHE_PORT", "redis-cache", "6379"),
		streamRedis: newRedisClient("REDIS_STREAM_HOST", "REDIS_STREAM_PORT", "redis-stream", "6379"),
	}
	defer a.cacheRedis.Close()
	defer a.streamRedis.Close()

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", a.healthz)
	mux.HandleFunc("/publish", a.publish)
	mux.HandleFunc("/subscribe", a.subscribe)
	mux.HandleFunc("/messages/", a.messages)
	mux.HandleFunc("/subscribers/", a.subscribers)
	mux.HandleFunc("/stats", a.stats)

	server := &http.Server{
		Addr:              ":8080",
		Handler:           a.loggingMiddleware(mux),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("service=%s event=startup port=8080", name)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("service=%s event=server_error error=%q", name, err.Error())
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	log.Printf("service=%s event=shutdown_start", name)
	if err := server.Shutdown(ctx); err != nil {
		log.Printf("service=%s event=shutdown_error error=%q", name, err.Error())
	}
	log.Printf("service=%s event=shutdown_complete", name)
}

func newRedisClient(hostEnv, portEnv, defaultHost, defaultPort string) *redis.Client {
	host := getenv(hostEnv, defaultHost)
	port := getenv(portEnv, defaultPort)
	return redis.NewClient(&redis.Options{Addr: host + ":" + port})
}

func getenv(name, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(name)); v != "" {
		return v
	}
	return fallback
}

func (a *app) loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		lw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(lw, r)
		log.Printf("service=%s operation=http_request method=%s path=%s status=%d latency_ms=%d", a.name, r.Method, routePath(r.URL.Path), lw.status, time.Since(start).Milliseconds())
	})
}

func routePath(path string) string {
	switch {
	case strings.HasPrefix(path, "/messages/"):
		return "/messages/{topic}"
	case strings.HasPrefix(path, "/subscribers/"):
		return "/subscribers/{topic}"
	default:
		return path
	}
}

func (a *app) healthz(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *app) publish(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req publishRequest
	if !decodeJSON(w, r, &req) {
		return
	}
	topic := strings.TrimSpace(req.Topic)
	if topic == "" {
		writeError(w, http.StatusBadRequest, "topic is required")
		return
	}

	payload, err := encodePayload(req.Payload)
	if err != nil {
		writeError(w, http.StatusBadRequest, "payload is invalid")
		return
	}

	ctx := r.Context()
	start := time.Now()
	id, err := a.streamRedis.XAdd(ctx, &redis.XAddArgs{
		Stream: "stream:" + topic,
		Values: map[string]interface{}{"payload": payload},
	}).Result()
	if err != nil {
		log.Printf("service=%s operation=publish dependency=redis-stream status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to publish message")
		return
	}
	log.Printf("service=%s operation=publish dependency=redis-stream status=ok latency_ms=%d", a.name, time.Since(start).Milliseconds())

	start = time.Now()
	count, err := a.cacheRedis.Incr(ctx, "pubcount:"+topic).Result()
	if err != nil {
		log.Printf("service=%s operation=publish_count dependency=redis-cache status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to update publish count")
		return
	}
	log.Printf("service=%s operation=publish_count dependency=redis-cache status=ok latency_ms=%d", a.name, time.Since(start).Milliseconds())

	writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "topic": topic, "count": count})
}

func encodePayload(v interface{}) (string, error) {
	if v == nil {
		return "null", nil
	}
	if s, ok := v.(string); ok {
		return s, nil
	}
	b, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func (a *app) subscribe(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		a.addSubscription(w, r)
	case http.MethodDelete:
		a.removeSubscription(w, r)
	default:
		methodNotAllowed(w)
	}
}

func (a *app) addSubscription(w http.ResponseWriter, r *http.Request) {
	req, ok := readSubscription(w, r)
	if !ok {
		return
	}
	ctx := r.Context()
	start := time.Now()
	pipe := a.cacheRedis.TxPipeline()
	pipe.SAdd(ctx, "subs:"+req.Topic, req.SubscriberID)
	pipe.SAdd(ctx, "topics:"+req.SubscriberID, req.Topic)
	_, err := pipe.Exec(ctx)
	if err != nil {
		log.Printf("service=%s operation=subscribe dependency=redis-cache status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to subscribe")
		return
	}
	log.Printf("service=%s operation=subscribe dependency=redis-cache status=ok latency_ms=%d", a.name, time.Since(start).Milliseconds())
	writeJSON(w, http.StatusOK, map[string]string{"subscriber_id": req.SubscriberID, "topic": req.Topic, "status": "subscribed"})
}

func (a *app) removeSubscription(w http.ResponseWriter, r *http.Request) {
	req, ok := readSubscription(w, r)
	if !ok {
		return
	}
	ctx := r.Context()
	start := time.Now()
	pipe := a.cacheRedis.TxPipeline()
	pipe.SRem(ctx, "subs:"+req.Topic, req.SubscriberID)
	pipe.SRem(ctx, "topics:"+req.SubscriberID, req.Topic)
	_, err := pipe.Exec(ctx)
	if err != nil {
		log.Printf("service=%s operation=unsubscribe dependency=redis-cache status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to unsubscribe")
		return
	}
	log.Printf("service=%s operation=unsubscribe dependency=redis-cache status=ok latency_ms=%d", a.name, time.Since(start).Milliseconds())
	writeJSON(w, http.StatusOK, map[string]string{"subscriber_id": req.SubscriberID, "topic": req.Topic, "status": "unsubscribed"})
}

func readSubscription(w http.ResponseWriter, r *http.Request) (subscriptionRequest, bool) {
	var req subscriptionRequest
	if !decodeJSON(w, r, &req) {
		return req, false
	}
	req.SubscriberID = strings.TrimSpace(req.SubscriberID)
	req.Topic = strings.TrimSpace(req.Topic)
	if req.SubscriberID == "" || req.Topic == "" {
		writeError(w, http.StatusBadRequest, "subscriber_id and topic are required")
		return req, false
	}
	return req, true
}

func (a *app) messages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	topic := strings.TrimSpace(strings.TrimPrefix(r.URL.Path, "/messages/"))
	if topic == "" || strings.Contains(topic, "/") {
		writeError(w, http.StatusBadRequest, "topic is required")
		return
	}
	count := parseCount(r.URL.Query().Get("count"), 20)

	start := time.Now()
	msgs, err := a.streamRedis.XRevRangeN(r.Context(), "stream:"+topic, "+", "-", int64(count)).Result()
	if err != nil {
		log.Printf("service=%s operation=messages dependency=redis-stream status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to read messages")
		return
	}
	log.Printf("service=%s operation=messages dependency=redis-stream status=ok latency_ms=%d count=%d", a.name, time.Since(start).Milliseconds(), len(msgs))

	out := make([]streamMessage, 0, len(msgs))
	for _, msg := range msgs {
		out = append(out, streamMessage{ID: msg.ID, Values: msg.Values})
	}
	writeJSON(w, http.StatusOK, out)
}

func parseCount(raw string, fallback int) int {
	if raw == "" {
		return fallback
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 1 {
		return fallback
	}
	if n > maxMessageCount {
		return maxMessageCount
	}
	return n
}

func (a *app) subscribers(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	topic := strings.TrimSpace(strings.TrimPrefix(r.URL.Path, "/subscribers/"))
	if topic == "" || strings.Contains(topic, "/") {
		writeError(w, http.StatusBadRequest, "topic is required")
		return
	}
	start := time.Now()
	subs, err := a.cacheRedis.SMembers(r.Context(), "subs:"+topic).Result()
	if err != nil {
		log.Printf("service=%s operation=subscribers dependency=redis-cache status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to read subscribers")
		return
	}
	log.Printf("service=%s operation=subscribers dependency=redis-cache status=ok latency_ms=%d count=%d", a.name, time.Since(start).Milliseconds(), len(subs))
	writeJSON(w, http.StatusOK, subs)
}

func (a *app) stats(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	ctx := r.Context()
	start := time.Now()
	stats := map[string]int64{}
	iter := a.cacheRedis.Scan(ctx, 0, "pubcount:*", 100).Iterator()
	for iter.Next(ctx) {
		key := iter.Val()
		value, err := a.cacheRedis.Get(ctx, key).Int64()
		if err != nil {
			log.Printf("service=%s operation=stats_get dependency=redis-cache status=error key_type=pubcount latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
			writeError(w, http.StatusBadGateway, "failed to read stats")
			return
		}
		stats[strings.TrimPrefix(key, "pubcount:")] = value
	}
	if err := iter.Err(); err != nil {
		log.Printf("service=%s operation=stats_scan dependency=redis-cache status=error latency_ms=%d error=%q", a.name, time.Since(start).Milliseconds(), err.Error())
		writeError(w, http.StatusBadGateway, "failed to read stats")
		return
	}
	log.Printf("service=%s operation=stats dependency=redis-cache status=ok latency_ms=%d count=%d", a.name, time.Since(start).Milliseconds(), len(stats))
	writeJSON(w, http.StatusOK, stats)
}

func decodeJSON(w http.ResponseWriter, r *http.Request, dst interface{}) bool {
	defer r.Body.Close()
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return false
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("event=response_encode_error error=%q", err.Error())
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func methodNotAllowed(w http.ResponseWriter) {
	writeError(w, http.StatusMethodNotAllowed, "method not allowed")
}
