package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "device-registry"

var (
	pg    *pgxpool.Pool
	cache *redis.Client
)

type Device struct {
	ID              int64  `json:"id"`
	DeviceID        string `json:"device_id"`
	Model           string `json:"model"`
	FirmwareVersion string `json:"firmware_version"`
	OwnerID         string `json:"owner_id"`
	RegisteredAt    string `json:"registered_at,omitempty"`
	UpdatedAt       string `json:"updated_at,omitempty"`
}

type DeviceIn struct {
	DeviceID        string `json:"device_id"`
	Model           string `json:"model"`
	FirmwareVersion string `json:"firmware_version"`
	OwnerID         string `json:"owner_id"`
}

type FirmwareIn struct {
	FirmwareVersion string `json:"firmware_version"`
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func cacheKey(deviceID string) string { return "device:" + deviceID }

func cacheSet(ctx context.Context, d *Device) {
	key := cacheKey(d.DeviceID)
	if err := cache.HSet(ctx, key, map[string]interface{}{
		"id":               d.ID,
		"device_id":        d.DeviceID,
		"model":            d.Model,
		"firmware_version": d.FirmwareVersion,
		"owner_id":         d.OwnerID,
	}).Err(); err != nil {
		log.Printf("ERROR %s: cache HSET: %v", SERVICE, err)
		return
	}
	if err := cache.Expire(ctx, key, 600*time.Second).Err(); err != nil {
		log.Printf("ERROR %s: cache EXPIRE: %v", SERVICE, err)
	}
}

func cacheDel(ctx context.Context, deviceID string) {
	if err := cache.Del(ctx, cacheKey(deviceID)).Err(); err != nil {
		log.Printf("ERROR %s: cache DEL: %v", SERVICE, err)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": SERVICE})
}

func upsertDevice(w http.ResponseWriter, r *http.Request) {
	var in DeviceIn
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad json"})
		return
	}
	if in.DeviceID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "device_id required"})
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	var d Device
	err := pg.QueryRow(ctx,
		`INSERT INTO devices(device_id, model, firmware_version, owner_id)
         VALUES($1,$2,$3,$4)
         ON CONFLICT (device_id) DO UPDATE
           SET model=EXCLUDED.model,
               firmware_version=EXCLUDED.firmware_version,
               owner_id=EXCLUDED.owner_id,
               updated_at=now()
         RETURNING id, device_id, model, firmware_version, owner_id,
                   registered_at::text, updated_at::text`,
		in.DeviceID, in.Model, in.FirmwareVersion, in.OwnerID,
	).Scan(&d.ID, &d.DeviceID, &d.Model, &d.FirmwareVersion, &d.OwnerID, &d.RegisteredAt, &d.UpdatedAt)
	if err != nil {
		log.Printf("ERROR %s: upsert device: %v", SERVICE, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
		return
	}
	cacheSet(ctx, &d)
	writeJSON(w, http.StatusOK, d)
}

func getDevice(w http.ResponseWriter, r *http.Request) {
	deviceID := chi.URLParam(r, "device_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	m, err := cache.HGetAll(ctx, cacheKey(deviceID)).Result()
	if err == nil && len(m) > 0 {
		writeJSON(w, http.StatusOK, map[string]string{
			"device_id":        m["device_id"],
			"model":            m["model"],
			"firmware_version": m["firmware_version"],
			"owner_id":         m["owner_id"],
			"source":           "cache",
		})
		return
	}

	var d Device
	err = pg.QueryRow(ctx,
		`SELECT id, device_id, model, firmware_version, owner_id,
                registered_at::text, updated_at::text
         FROM devices WHERE device_id=$1`,
		deviceID,
	).Scan(&d.ID, &d.DeviceID, &d.Model, &d.FirmwareVersion, &d.OwnerID, &d.RegisteredAt, &d.UpdatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
			return
		}
		log.Printf("ERROR %s: get device: %v", SERVICE, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
		return
	}
	cacheSet(ctx, &d)
	writeJSON(w, http.StatusOK, d)
}

func updateFirmware(w http.ResponseWriter, r *http.Request) {
	deviceID := chi.URLParam(r, "device_id")
	var in FirmwareIn
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil || in.FirmwareVersion == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "firmware_version required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	tag, err := pg.Exec(ctx,
		`UPDATE devices SET firmware_version=$1, updated_at=now() WHERE device_id=$2`,
		in.FirmwareVersion, deviceID,
	)
	if err != nil {
		log.Printf("ERROR %s: update firmware: %v", SERVICE, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
		return
	}
	if tag.RowsAffected() == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	cacheDel(ctx, deviceID)
	writeJSON(w, http.StatusOK, map[string]string{
		"device_id":        deviceID,
		"firmware_version": in.FirmwareVersion,
	})
}

func devicesByOwner(w http.ResponseWriter, r *http.Request) {
	ownerID := chi.URLParam(r, "owner_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	rows, err := pg.Query(ctx,
		`SELECT id, device_id, model, firmware_version, owner_id,
                registered_at::text, updated_at::text
         FROM devices WHERE owner_id=$1 ORDER BY registered_at DESC LIMIT 100`,
		ownerID,
	)
	if err != nil {
		log.Printf("ERROR %s: devices by owner: %v", SERVICE, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
		return
	}
	defer rows.Close()

	out := []Device{}
	for rows.Next() {
		var d Device
		if err := rows.Scan(&d.ID, &d.DeviceID, &d.Model, &d.FirmwareVersion, &d.OwnerID, &d.RegisteredAt, &d.UpdatedAt); err != nil {
			log.Printf("ERROR %s: scan row: %v", SERVICE, err)
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
			return
		}
		out = append(out, d)
	}
	writeJSON(w, http.StatusOK, out)
}

func deleteDevice(w http.ResponseWriter, r *http.Request) {
	deviceID := chi.URLParam(r, "device_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	tag, err := pg.Exec(ctx, `DELETE FROM devices WHERE device_id=$1`, deviceID)
	if err != nil {
		log.Printf("ERROR %s: delete device: %v", SERVICE, err)
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "db error"})
		return
	}
	if tag.RowsAffected() == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}
	cacheDel(ctx, deviceID)
	writeJSON(w, http.StatusOK, map[string]string{"deleted": deviceID})
}

func mustEnv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	dsn := mustEnv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
	redisURL := mustEnv("REDIS_URL", "redis://redis-cache:6379")

	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		log.Fatalf("ERROR %s: parse pg dsn: %v", SERVICE, err)
	}
	cfg.MaxConns = 8
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second

	pgCtx, pgCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer pgCancel()
	pg, err = pgxpool.NewWithConfig(pgCtx, cfg)
	if err != nil {
		log.Fatalf("ERROR %s: pg connect: %v", SERVICE, err)
	}
	defer pg.Close()

	ddlCtx, ddlCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer ddlCancel()
	if _, err := pg.Exec(ddlCtx,
		`CREATE TABLE IF NOT EXISTS devices(
            id BIGSERIAL PRIMARY KEY,
            device_id TEXT UNIQUE NOT NULL,
            model TEXT,
            firmware_version TEXT,
            owner_id TEXT,
            registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`,
	); err != nil {
		log.Printf("ERROR %s: create table: %v", SERVICE, err)
	}

	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("ERROR %s: parse redis url: %v", SERVICE, err)
	}
	opt.DialTimeout = 2 * time.Second
	opt.ReadTimeout = 2 * time.Second
	opt.WriteTimeout = 2 * time.Second
	cache = redis.NewClient(opt)

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/devices", upsertDevice)
	r.Get("/devices/owner/{owner_id}", devicesByOwner)
	r.Get("/devices/{device_id}", getDevice)
	r.Put("/devices/{device_id}/firmware", updateFirmware)
	r.Delete("/devices/{device_id}", deleteDevice)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Fatalf("ERROR %s: server: %v", SERVICE, err)
	}
}
