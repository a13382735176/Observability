package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	defaultPort = "8080"
	ttlSeconds  = 86400
)

type sessionResponse struct {
	Valid     bool   `json:"valid"`
	UserID    string `json:"user_id,omitempty"`
	IP        string `json:"ip,omitempty"`
	UA        string `json:"ua,omitempty"`
	CreatedAt string `json:"created_at,omitempty"`
}

type app struct {
	name         string
	cacheClient  *redis.Client
	streamClient *redis.Client
	logger       *slog.Logger
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	application := &app{
		name:         env("APP_NAME", "session-manager-skill"),
		cacheClient:  newRedisClient(env("REDIS_CACHE_HOST", "redis-cache"), env("REDIS_CACHE_PORT", "6379")),
		streamClient: newRedisClient(env("REDIS_STREAM_HOST", "redis-stream"), env("REDIS_STREAM_PORT", "6379")),
		logger:       logger,
	}
	defer application.cacheClient.Close()
	defer application.streamClient.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	if err := application.cacheClient.Ping(ctx).Err(); err != nil {
		logger.Warn("redis dependency ping failed", "service", application.name, "dependency", "redis-cache", "error", err.Error())
	}
	if err := application.streamClient.Ping(ctx).Err(); err != nil {
		logger.Warn("redis dependency ping failed", "service", application.name, "dependency", "redis-stream", "error", err.Error())
	}
	cancel()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", application.healthz)
	mux.HandleFunc("GET /sessions/user/{user_id}", application.getUserSessions)
	mux.HandleFunc("GET /sessions/{session_id}", application.getSession)
	mux.HandleFunc("POST /sessions/{session_id}/refresh", application.refreshSession)

	server := &http.Server{
		Addr:              ":" + env("PORT", defaultPort),
		Handler:           application.withRequestLogging(mux),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("service starting", "service", application.name, "port", strings.TrimPrefix(server.Addr, ":"))
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("service stopped unexpectedly", "service", application.name, "error", err.Error())
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	logger.Info("service shutting down", "service", application.name)
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", "service", application.name, "error", err.Error())
		os.Exit(1)
	}
}

func env(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func newRedisClient(host, port string) *redis.Client {
	return redis.NewClient(&redis.Options{Addr: fmt.Sprintf("%s:%s", host, port)})
}

func (a *app) healthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (a *app) getSession(w http.ResponseWriter, r *http.Request) {
	sessionID := r.PathValue("session_id")
	result, status, err := a.readSession(r.Context(), sessionID)
	if err != nil {
		a.logger.Error("session lookup failed", "service", a.name, "operation", "get_session", "dependency", "redis-cache", "status", status, "error", err.Error())
		writeError(w, http.StatusInternalServerError, "session lookup failed")
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (a *app) getUserSessions(w http.ResponseWriter, r *http.Request) {
	userID := r.PathValue("user_id")
	key := "user_sess:" + userID

	ids, err := a.cacheClient.SMembers(r.Context(), key).Result()
	if err != nil {
		a.logger.Error("user session index lookup failed", "service", a.name, "operation", "get_user_sessions", "dependency", "redis-cache", "error", err.Error())
		writeError(w, http.StatusInternalServerError, "user session lookup failed")
		return
	}

	sessions := make([]sessionResponse, 0, len(ids))
	missing := 0
	for _, id := range ids {
		session, _, err := a.readSession(r.Context(), id)
		if err != nil {
			a.logger.Error("indexed session lookup failed", "service", a.name, "operation", "get_user_sessions", "dependency", "redis-cache", "error", err.Error())
			writeError(w, http.StatusInternalServerError, "user session lookup failed")
			return
		}
		if session.Valid {
			sessions = append(sessions, session)
		} else {
			missing++
		}
	}
	if missing > 0 {
		a.logger.Info("user session index contained missing sessions", "service", a.name, "operation", "get_user_sessions", "missing_count", missing)
	}
	writeJSON(w, http.StatusOK, sessions)
}

func (a *app) refreshSession(w http.ResponseWriter, r *http.Request) {
	sessionID := r.PathValue("session_id")
	key := "sess:" + sessionID

	ok, err := a.cacheClient.Expire(r.Context(), key, ttlSeconds*time.Second).Result()
	if err != nil {
		a.logger.Error("session refresh failed", "service", a.name, "operation", "refresh_session", "dependency", "redis-cache", "error", err.Error())
		writeError(w, http.StatusInternalServerError, "session refresh failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"refreshed": ok})
}

func (a *app) readSession(ctx context.Context, sessionID string) (sessionResponse, string, error) {
	value, err := a.cacheClient.Get(ctx, "sess:"+sessionID).Result()
	if errors.Is(err, redis.Nil) {
		return sessionResponse{Valid: false}, "miss", nil
	}
	if err != nil {
		return sessionResponse{}, "error", err
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(value), &payload); err != nil {
		return sessionResponse{}, "decode_error", err
	}

	return sessionResponse{
		Valid:     true,
		UserID:    stringField(payload, "user_id"),
		IP:        stringField(payload, "ip"),
		UA:        stringField(payload, "ua"),
		CreatedAt: stringField(payload, "created_at"),
	}, "hit", nil
}

func stringField(payload map[string]any, name string) string {
	if value, ok := payload[name]; ok && value != nil {
		switch v := value.(type) {
		case string:
			return v
		case json.Number:
			return v.String()
		default:
			return fmt.Sprint(v)
		}
	}
	return ""
}

func (a *app) withRequestLogging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(recorder, r)
		a.logger.Info("http request completed",
			"service", a.name,
			"method", r.Method,
			"path", routePath(r),
			"status", recorder.status,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

func routePath(r *http.Request) string {
	if pattern := r.Pattern; pattern != "" {
		return pattern
	}
	return r.URL.Path
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
