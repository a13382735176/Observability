package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	_ "github.com/lib/pq"
)

const (
	defaultAppName = "audit-log-skill"
	defaultPGDSN   = "postgres://vibe:vibe@postgres:5432/vibe?sslmode=disable"
	listenAddr     = ":8080"
)

const schemaSQL = `CREATE TABLE IF NOT EXISTS audit_log(
    id bigserial PRIMARY KEY,
    actor text,
    action text,
    resource text,
    success boolean DEFAULT true,
    metadata jsonb DEFAULT '{}'::jsonb,
    ts timestamptz DEFAULT now()
);`

type app struct {
	name   string
	db     *sql.DB
	logger *jsonLogger
}

type jsonLogger struct {
	service string
}

func main() {
	name := getenv("APP_NAME", defaultAppName)
	logger := &jsonLogger{service: name}
	dsn := normalizePostgresDSN(getenv("PG_DSN", defaultPGDSN))

	logger.info("service_starting", fields{"operation": "startup", "addr": listenAddr})

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		logger.error("postgres_open_failed", err, fields{"operation": "startup", "dependency": "postgres"})
		os.Exit(1)
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)

	if err := initSchema(context.Background(), db, logger); err != nil {
		logger.error("postgres_schema_init_failed", err, fields{"operation": "startup", "dependency": "postgres"})
		os.Exit(1)
	}

	application := &app{name: name, db: db, logger: logger}
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", application.healthz)

	server := &http.Server{
		Addr:              listenAddr,
		Handler:           requestLogMiddleware(logger, mux),
		ReadHeaderTimeout: 5 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		logger.info("http_server_listening", fields{"operation": "listen", "addr": listenAddr})
		errCh <- server.ListenAndServe()
	}()

	stopCh := make(chan os.Signal, 1)
	signal.Notify(stopCh, syscall.SIGINT, syscall.SIGTERM)

	select {
	case sig := <-stopCh:
		logger.info("service_stopping", fields{"operation": "shutdown", "signal": sig.String()})
	case err := <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			logger.error("http_server_failed", err, fields{"operation": "listen"})
			os.Exit(1)
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		logger.error("http_server_shutdown_failed", err, fields{"operation": "shutdown"})
	}
	if err := db.Close(); err != nil {
		logger.error("postgres_close_failed", err, fields{"operation": "shutdown", "dependency": "postgres"})
	}
	logger.info("service_stopped", fields{"operation": "shutdown"})
}

func initSchema(parent context.Context, db *sql.DB, logger *jsonLogger) error {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()

	start := time.Now()
	if err := db.PingContext(ctx); err != nil {
		logger.error("postgres_ping_failed", err, fields{"operation": "schema_init", "dependency": "postgres", "latency_ms": elapsedMillis(start)})
		return err
	}
	if _, err := db.ExecContext(ctx, schemaSQL); err != nil {
		logger.error("postgres_schema_exec_failed", err, fields{"operation": "schema_init", "dependency": "postgres", "latency_ms": elapsedMillis(start)})
		return err
	}
	logger.info("postgres_schema_ready", fields{"operation": "schema_init", "dependency": "postgres", "latency_ms": elapsedMillis(start)})
	return nil
}

func (a *app) healthz(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	start := time.Now()
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	dbStatus := "ok"
	statusCode := http.StatusOK
	if err := a.db.PingContext(ctx); err != nil {
		dbStatus = "unavailable"
		statusCode = http.StatusServiceUnavailable
		a.logger.error("health_check_failed", err, fields{"operation": "healthz", "dependency": "postgres", "latency_ms": elapsedMillis(start)})
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"status":   statusText(statusCode),
		"service":  a.name,
		"postgres": dbStatus,
	})
}

func requestLogMiddleware(logger *jsonLogger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		logger.info("http_request_completed", fields{
			"operation":   "http_request",
			"method":      r.Method,
			"path":        r.URL.Path,
			"status":      rw.status,
			"latency_ms":  elapsedMillis(start),
			"remote_addr": remoteHost(r.RemoteAddr),
		})
	})
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(status int) {
	rw.status = status
	rw.ResponseWriter.WriteHeader(status)
}

type fields map[string]interface{}

func (l *jsonLogger) info(message string, f fields) {
	l.emit("info", message, nil, f)
}

func (l *jsonLogger) error(message string, err error, f fields) {
	l.emit("error", message, err, f)
}

func (l *jsonLogger) emit(level, message string, err error, f fields) {
	record := map[string]interface{}{
		"ts":      time.Now().UTC().Format(time.RFC3339Nano),
		"level":   level,
		"service": l.service,
		"message": message,
	}
	for k, v := range f {
		record[k] = v
	}
	if err != nil {
		record["error"] = err.Error()
	}
	b, marshalErr := json.Marshal(record)
	if marshalErr != nil {
		log.Printf(`{"level":"error","service":"%s","message":"log_marshal_failed","error":"%s"}`, l.service, marshalErr.Error())
		return
	}
	log.Print(string(b))
}

func getenv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func normalizePostgresDSN(dsn string) string {
	if strings.HasPrefix(dsn, "postgres://") || strings.HasPrefix(dsn, "postgresql://") {
		if strings.Contains(dsn, "sslmode=") {
			return dsn
		}
		sep := "?"
		if strings.Contains(dsn, "?") {
			sep = "&"
		}
		return dsn + sep + "sslmode=disable"
	}
	return dsn
}

func statusText(code int) string {
	if code >= 200 && code < 300 {
		return "ok"
	}
	return "unavailable"
}

func elapsedMillis(start time.Time) int64 {
	return time.Since(start).Milliseconds()
}

func remoteHost(remoteAddr string) string {
	if i := strings.LastIndex(remoteAddr, ":"); i > 0 {
		return remoteAddr[:i]
	}
	return remoteAddr
}
