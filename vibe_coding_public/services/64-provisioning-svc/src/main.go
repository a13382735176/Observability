package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
	"github.com/jackc/pgx/v5"
)

var db *pgx.Conn
var rdb *redis.Client

func main() {
	dsn := os.Getenv("PG_DSN")
	if dsn == "" {
		dsn = "postgres://vibe:vibe@postgres:5432/vibe"
	}
	ctx := context.Background()
	var err error
	db, err = pgx.Connect(ctx, dsn)
	if err != nil {
		log.Printf("provisioning-svc: pg connect: %v", err)
	} else {
		ensureTable(ctx)
	}

	cacheHost := os.Getenv("REDIS_CACHE_HOST")
	if cacheHost == "" {
		cacheHost = "redis-cache"
	}
	rdb = redis.NewClient(&redis.Options{
		Addr:         cacheHost + ":6379",
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/provision", provision)
	r.Get("/provision/{device_id}", getProvision)

	log.Println("provisioning-svc listening on 8080")
	http.ListenAndServe("0.0.0.0:8080", r)
}

func ensureTable(ctx context.Context) {
	_, err := db.Exec(ctx, `CREATE TABLE IF NOT EXISTS provisions(
		id serial PRIMARY KEY,
		device_id text UNIQUE,
		device_type text,
		api_token text,
		provisioned_at timestamptz DEFAULT now()
	)`)
	if err != nil {
		log.Printf("provisioning-svc: ensure_table: %v", err)
	}
}

func healthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": "provisioning-svc"})
}

func provision(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DeviceID   string `json:"device_id"`
		DeviceType string `json:"device_type"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", 400)
		return
	}
	token := genToken()
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	_, err := db.Exec(ctx,
		`INSERT INTO provisions(device_id, device_type, api_token) VALUES($1,$2,$3)
		 ON CONFLICT(device_id) DO UPDATE SET device_type=$2, api_token=$3`,
		req.DeviceID, req.DeviceType, token)
	if err != nil {
		log.Printf("provisioning-svc: db: %v", err)
		http.Error(w, `{"error":"db error"}`, 503)
		return
	}
	cctx, ccancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer ccancel()
	rdb.Set(cctx, "token:"+req.DeviceID, token, 24*time.Hour)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(201)
	json.NewEncoder(w).Encode(map[string]string{"device_id": req.DeviceID, "api_token": token})
}

func getProvision(w http.ResponseWriter, r *http.Request) {
	devID := chi.URLParam(r, "device_id")
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var row struct {
		DeviceID      string    `json:"device_id"`
		DeviceType    string    `json:"device_type"`
		APIToken      string    `json:"api_token"`
		ProvisionedAt time.Time `json:"provisioned_at"`
	}
	err := db.QueryRow(ctx, `SELECT device_id,device_type,api_token,provisioned_at FROM provisions WHERE device_id=$1`, devID).
		Scan(&row.DeviceID, &row.DeviceType, &row.APIToken, &row.ProvisionedAt)
	if err != nil {
		log.Printf("provisioning-svc: db: %v", err)
		http.Error(w, `{"error":"not found"}`, 404)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(row)
}

func genToken() string {
	b := make([]byte, 16)
	rand.Read(b)
	return hex.EncodeToString(b)
}
