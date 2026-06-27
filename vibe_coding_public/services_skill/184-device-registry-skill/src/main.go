package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"
)

const (
	serviceName = "device-registry"
	cacheTTL    = 600 * time.Second
)

type device struct {
	ID              int64     `json:"id,omitempty"`
	DeviceID        string    `json:"device_id"`
	Model           string    `json:"model,omitempty"`
	FirmwareVersion string    `json:"firmware_version,omitempty"`
	OwnerID         string    `json:"owner_id,omitempty"`
	RegisteredAt    time.Time `json:"registered_at,omitempty"`
	UpdatedAt       time.Time `json:"updated_at,omitempty"`
}

type deviceRequest struct {
	DeviceID        string `json:"device_id"`
	Model           string `json:"model"`
	FirmwareVersion string `json:"firmware_version"`
	OwnerID         string `json:"owner_id"`
}

type firmwareRequest struct {
	FirmwareVersion string `json:"firmware_version"`
}

type app struct {
	db    *sql.DB
	redis *redis.Client
}

func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)

	ctx := context.Background()
	pgDSN := getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe?sslmode=disable")
	db, err := sql.Open("postgres", pgDSN)
	if err != nil {
		log.Fatalf("service=%s event=startup dependency=postgres status=error error=%q", serviceName, err.Error())
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(30 * time.Minute)

	if err := initSchema(ctx, db); err != nil {
		log.Fatalf("service=%s event=schema_init dependency=postgres status=error error=%q", serviceName, err.Error())
	}

	rdb := newRedisClient()
	if rdb != nil {
		pingCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		if err := rdb.Ping(pingCtx).Err(); err != nil {
			log.Printf("service=%s event=startup dependency=redis status=degraded error=%q", serviceName, err.Error())
		} else {
			log.Printf("service=%s event=startup dependency=redis status=ok", serviceName)
		}
		cancel()
	}

	a := &app{db: db, redis: rdb}
	srv := &http.Server{
		Addr:              ":8080",
		Handler:           loggingMiddleware(a.routes()),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("service=%s event=startup status=ok port=8080", serviceName)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("service=%s event=listen status=error error=%q", serviceName, err.Error())
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("service=%s event=shutdown status=error error=%q", serviceName, err.Error())
	} else {
		log.Printf("service=%s event=shutdown status=ok", serviceName)
	}
	if rdb != nil {
		_ = rdb.Close()
	}
	_ = db.Close()
}

func getenv(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func newRedisClient() *redis.Client {
	raw := os.Getenv("REDIS_URL")
	if raw == "" {
		raw = "redis://redis-cache:6379"
	}
	opt, err := redis.ParseURL(raw)
	if err != nil {
		log.Printf("service=%s event=redis_config status=error error=%q", serviceName, err.Error())
		return nil
	}
	return redis.NewClient(opt)
}

func initSchema(ctx context.Context, db *sql.DB) error {
	_, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS devices(
id BIGSERIAL PRIMARY KEY,
device_id TEXT UNIQUE NOT NULL,
model TEXT,
firmware_version TEXT,
owner_id TEXT,
registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`)
	return err
}

func (a *app) routes() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimSuffix(r.URL.Path, "/")
		if path == "" {
			path = "/"
		}
		switch {
		case r.Method == http.MethodGet && path == "/healthz":
			a.healthz(w, r)
		case r.Method == http.MethodPost && path == "/devices":
			a.createOrUpdateDevice(w, r)
		case r.Method == http.MethodGet && strings.HasPrefix(path, "/devices/owner/"):
			ownerID := strings.TrimPrefix(path, "/devices/owner/")
			a.devicesByOwner(w, withPathValue(r, "owner_id", ownerID))
		case r.Method == http.MethodGet && strings.HasPrefix(path, "/devices/") && !strings.Contains(strings.TrimPrefix(path, "/devices/"), "/"):
			deviceID := strings.TrimPrefix(path, "/devices/")
			a.getDevice(w, withPathValue(r, "device_id", deviceID))
		case r.Method == http.MethodPut && strings.HasPrefix(path, "/devices/") && strings.HasSuffix(path, "/firmware"):
			deviceID := strings.TrimSuffix(strings.TrimPrefix(path, "/devices/"), "/firmware")
			a.updateFirmware(w, withPathValue(r, "device_id", deviceID))
		case r.Method == http.MethodDelete && strings.HasPrefix(path, "/devices/") && !strings.Contains(strings.TrimPrefix(path, "/devices/"), "/"):
			deviceID := strings.TrimPrefix(path, "/devices/")
			a.deleteDevice(w, withPathValue(r, "device_id", deviceID))
		default:
			writeError(w, http.StatusNotFound, "not_found")
		}
	})
}

func (a *app) healthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": serviceName})
}

type pathValueKey string

func withPathValue(r *http.Request, name, value string) *http.Request {
	ctx := context.WithValue(r.Context(), pathValueKey(name), value)
	return r.WithContext(ctx)
}

func pathValue(r *http.Request, name string) string {
	v, _ := r.Context().Value(pathValueKey(name)).(string)
	return v
}

func (a *app) createOrUpdateDevice(w http.ResponseWriter, r *http.Request) {
	var req deviceRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	req.DeviceID = strings.TrimSpace(req.DeviceID)
	if req.DeviceID == "" {
		writeError(w, http.StatusBadRequest, "device_id_required")
		return
	}

	ctx := r.Context()
	start := time.Now()
	row := a.db.QueryRowContext(ctx, `INSERT INTO devices(device_id, model, firmware_version, owner_id, updated_at)
VALUES($1, $2, $3, $4, now())
ON CONFLICT(device_id) DO UPDATE SET
model = EXCLUDED.model,
firmware_version = EXCLUDED.firmware_version,
owner_id = EXCLUDED.owner_id,
updated_at = now()
RETURNING id, device_id, model, firmware_version, owner_id, registered_at, updated_at`,
		req.DeviceID, req.Model, req.FirmwareVersion, req.OwnerID)
	d, err := scanDevice(row)
	logDependency("postgres", "upsert_device", start, err)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	a.cacheSet(ctx, d)
	writeJSON(w, http.StatusOK, d)
}

func (a *app) getDevice(w http.ResponseWriter, r *http.Request) {
	deviceID := strings.TrimSpace(pathValue(r, "device_id"))
	if deviceID == "" {
		writeError(w, http.StatusBadRequest, "device_id_required")
		return
	}
	ctx := r.Context()
	if d, ok := a.cacheGet(ctx, deviceID); ok {
		writeJSON(w, http.StatusOK, d)
		return
	}

	start := time.Now()
	row := a.db.QueryRowContext(ctx, `SELECT id, device_id, model, firmware_version, owner_id, registered_at, updated_at
FROM devices WHERE device_id = $1`, deviceID)
	d, err := scanDevice(row)
	logDependency("postgres", "select_device", start, err)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "device_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	a.cacheSet(ctx, d)
	writeJSON(w, http.StatusOK, d)
}

func (a *app) updateFirmware(w http.ResponseWriter, r *http.Request) {
	deviceID := strings.TrimSpace(pathValue(r, "device_id"))
	if deviceID == "" {
		writeError(w, http.StatusBadRequest, "device_id_required")
		return
	}
	var req firmwareRequest
	if err := decodeJSON(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}

	ctx := r.Context()
	start := time.Now()
	row := a.db.QueryRowContext(ctx, `UPDATE devices SET firmware_version = $1, updated_at = now()
WHERE device_id = $2
RETURNING id, device_id, model, firmware_version, owner_id, registered_at, updated_at`, req.FirmwareVersion, deviceID)
	d, err := scanDevice(row)
	logDependency("postgres", "update_firmware", start, err)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "device_not_found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	a.cacheDelete(ctx, deviceID)
	writeJSON(w, http.StatusOK, d)
}

func (a *app) devicesByOwner(w http.ResponseWriter, r *http.Request) {
	ownerID := strings.TrimSpace(pathValue(r, "owner_id"))
	if ownerID == "" {
		writeError(w, http.StatusBadRequest, "owner_id_required")
		return
	}
	ctx := r.Context()
	start := time.Now()
	rows, err := a.db.QueryContext(ctx, `SELECT id, device_id, model, firmware_version, owner_id, registered_at, updated_at
FROM devices WHERE owner_id = $1 ORDER BY updated_at DESC LIMIT 100`, ownerID)
	logDependency("postgres", "select_owner_devices", start, err)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	defer rows.Close()

	devices := make([]device, 0)
	for rows.Next() {
		d, err := scanDevice(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "database_error")
			return
		}
		devices = append(devices, d)
	}
	if err := rows.Err(); err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	writeJSON(w, http.StatusOK, devices)
}

func (a *app) deleteDevice(w http.ResponseWriter, r *http.Request) {
	deviceID := strings.TrimSpace(pathValue(r, "device_id"))
	if deviceID == "" {
		writeError(w, http.StatusBadRequest, "device_id_required")
		return
	}
	ctx := r.Context()
	start := time.Now()
	res, err := a.db.ExecContext(ctx, `DELETE FROM devices WHERE device_id = $1`, deviceID)
	logDependency("postgres", "delete_device", start, err)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "database_error")
		return
	}
	deleted, _ := res.RowsAffected()
	a.cacheDelete(ctx, deviceID)
	if deleted == 0 {
		writeError(w, http.StatusNotFound, "device_not_found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"deleted": true})
}

func (a *app) cacheGet(ctx context.Context, deviceID string) (device, bool) {
	if a.redis == nil {
		return device{}, false
	}
	start := time.Now()
	vals, err := a.redis.HGetAll(ctx, cacheKey(deviceID)).Result()
	logDependency("redis", "hgetall_device", start, err)
	if err != nil || len(vals) == 0 {
		return device{}, false
	}
	d, err := deviceFromHash(vals)
	if err != nil {
		log.Printf("service=%s operation=cache_decode dependency=redis status=error", serviceName)
		return device{}, false
	}
	return d, true
}

func (a *app) cacheSet(ctx context.Context, d device) {
	if a.redis == nil {
		return
	}
	fields := map[string]any{
		"id":               fmt.Sprint(d.ID),
		"device_id":        d.DeviceID,
		"model":            d.Model,
		"firmware_version": d.FirmwareVersion,
		"owner_id":         d.OwnerID,
		"registered_at":    d.RegisteredAt.Format(time.RFC3339Nano),
		"updated_at":       d.UpdatedAt.Format(time.RFC3339Nano),
	}
	start := time.Now()
	pipe := a.redis.Pipeline()
	pipe.HSet(ctx, cacheKey(d.DeviceID), fields)
	pipe.Expire(ctx, cacheKey(d.DeviceID), cacheTTL)
	_, err := pipe.Exec(ctx)
	logDependency("redis", "hset_expire_device", start, err)
}

func (a *app) cacheDelete(ctx context.Context, deviceID string) {
	if a.redis == nil {
		return
	}
	start := time.Now()
	err := a.redis.Del(ctx, cacheKey(deviceID)).Err()
	logDependency("redis", "del_device", start, err)
}

func cacheKey(deviceID string) string {
	return "device:" + deviceID
}

type scanner interface {
	Scan(dest ...any) error
}

func scanDevice(s scanner) (device, error) {
	var d device
	var model, firmware, owner sql.NullString
	err := s.Scan(&d.ID, &d.DeviceID, &model, &firmware, &owner, &d.RegisteredAt, &d.UpdatedAt)
	if model.Valid {
		d.Model = model.String
	}
	if firmware.Valid {
		d.FirmwareVersion = firmware.String
	}
	if owner.Valid {
		d.OwnerID = owner.String
	}
	return d, err
}

func deviceFromHash(vals map[string]string) (device, error) {
	var d device
	d.DeviceID = vals["device_id"]
	d.Model = vals["model"]
	d.FirmwareVersion = vals["firmware_version"]
	d.OwnerID = vals["owner_id"]
	_, _ = fmt.Sscan(vals["id"], &d.ID)
	if vals["registered_at"] != "" {
		t, err := time.Parse(time.RFC3339Nano, vals["registered_at"])
		if err != nil {
			return d, err
		}
		d.RegisteredAt = t
	}
	if vals["updated_at"] != "" {
		t, err := time.Parse(time.RFC3339Nano, vals["updated_at"])
		if err != nil {
			return d, err
		}
		d.UpdatedAt = t
	}
	if d.DeviceID == "" {
		return d, errors.New("missing cached device_id")
	}
	return d, nil
}

func decodeJSON(r *http.Request, dst any) error {
	defer r.Body.Close()
	dec := json.NewDecoder(r.Body)
	return dec.Decode(dst)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"error": code})
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		log.Printf("service=%s operation=http_request method=%s path=%s status=%d duration_ms=%d", serviceName, r.Method, routePath(r), rw.status, time.Since(start).Milliseconds())
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

func routePath(r *http.Request) string {
	p := r.URL.Path
	if strings.HasPrefix(p, "/devices/owner/") {
		return "/devices/owner/{owner_id}"
	}
	if strings.HasSuffix(p, "/firmware") && strings.HasPrefix(p, "/devices/") {
		return "/devices/{device_id}/firmware"
	}
	if strings.HasPrefix(p, "/devices/") {
		return "/devices/{device_id}"
	}
	return p
}

func logDependency(dep, operation string, start time.Time, err error) {
	status := "ok"
	if err != nil && !errors.Is(err, sql.ErrNoRows) && err != redis.Nil {
		status = "error"
	}
	log.Printf("service=%s operation=%s dependency=%s status=%s duration_ms=%d", serviceName, operation, dep, status, time.Since(start).Milliseconds())
}
