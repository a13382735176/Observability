package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "audit-log"

type AuditRow struct {
	ID       int64                  `json:"id"`
	Actor    string                 `json:"actor"`
	Action   string                 `json:"action"`
	Resource string                 `json:"resource"`
	Success  bool                   `json:"success"`
	Metadata map[string]interface{} `json:"metadata"`
	TS       time.Time              `json:"ts"`
}

var (
	pg  *pgxpool.Pool
	rdb *redis.Client
)

func main() {
	pgDSN := getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
	redisAddr := getenv("REDIS_ADDR", "redis-stream:6379")

	cfg, err := pgxpool.ParseConfig(pgDSN)
	if err != nil {
		log.Printf("ERROR %s: parse pg dsn: %v", SERVICE, err)
		os.Exit(1)
	}
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	cfg.MaxConns = 4

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	pg, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Printf("ERROR %s: pg connect: %v", SERVICE, err)
		os.Exit(1)
	}
	defer pg.Close()

	if _, err := pg.Exec(context.Background(), `
		CREATE TABLE IF NOT EXISTS audit_log(
			id        bigserial PRIMARY KEY,
			actor     text,
			action    text,
			resource  text,
			success   boolean DEFAULT true,
			metadata  jsonb DEFAULT '{}'::jsonb,
			ts        timestamptz DEFAULT now()
		);
		CREATE INDEX IF NOT EXISTS audit_log_actor_ts_idx    ON audit_log(actor, ts DESC);
		CREATE INDEX IF NOT EXISTS audit_log_resource_ts_idx ON audit_log(resource, ts DESC);
		CREATE INDEX IF NOT EXISTS audit_log_success_ts_idx  ON audit_log(success, ts DESC);
	`); err != nil {
		log.Printf("ERROR %s: create table: %v", SERVICE, err)
	}

	rdb = redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/audit", postAudit)
	r.Get("/audit/recent", recent)
	r.Get("/audit/failures", failures)
	r.Get("/audit/{id}", getOne)
	r.Get("/audit/actor/{actor}", byActor)
	r.Get("/audit/resource/{resource}", byResource)

	addr := "0.0.0.0:8080"
	log.Printf("%s: listening on %s", SERVICE, addr)
	if err := http.ListenAndServe(addr, r); err != nil {
		log.Printf("ERROR %s: server: %v", SERVICE, err)
	}
}

func getenv(k, dflt string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return dflt
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]string{"status": "ok", "service": SERVICE})
}

func postAudit(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Actor    string                 `json:"actor"`
		Action   string                 `json:"action"`
		Resource string                 `json:"resource"`
		Success  *bool                  `json:"success"`
		Metadata map[string]interface{} `json:"metadata"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 400, map[string]string{"error": "invalid json"})
		return
	}
	if body.Actor == "" || body.Action == "" || body.Resource == "" {
		writeJSON(w, 400, map[string]string{"error": "actor, action, resource required"})
		return
	}
	success := true
	if body.Success != nil {
		success = *body.Success
	}
	meta, _ := json.Marshal(body.Metadata)
	if len(meta) == 0 {
		meta = []byte("{}")
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var id int64
	var ts time.Time
	err := pg.QueryRow(ctx,
		`INSERT INTO audit_log(actor, action, resource, success, metadata) VALUES($1,$2,$3,$4,$5::jsonb) RETURNING id, ts`,
		body.Actor, body.Action, body.Resource, success, string(meta)).Scan(&id, &ts)
	if err != nil {
		log.Printf("ERROR %s: insert: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "db error"})
		return
	}

	// Best-effort stream publish.
	rctx, rcancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer rcancel()
	if err := rdb.XAdd(rctx, &redis.XAddArgs{
		Stream: "events:audit",
		Values: map[string]interface{}{
			"id":       strconv.FormatInt(id, 10),
			"actor":    body.Actor,
			"action":   body.Action,
			"resource": body.Resource,
			"success":  fmt.Sprintf("%t", success),
		},
	}).Err(); err != nil {
		log.Printf("ERROR %s: xadd events:audit: %v", SERVICE, err)
	}
	if !success {
		if err := rdb.XAdd(rctx, &redis.XAddArgs{
			Stream: "events:audit_failures",
			Values: map[string]interface{}{
				"id":       strconv.FormatInt(id, 10),
				"actor":    body.Actor,
				"action":   body.Action,
				"resource": body.Resource,
			},
		}).Err(); err != nil {
			log.Printf("ERROR %s: xadd events:audit_failures: %v", SERVICE, err)
		}
	}

	writeJSON(w, 201, map[string]interface{}{
		"id":       id,
		"actor":    body.Actor,
		"action":   body.Action,
		"resource": body.Resource,
		"success":  success,
		"ts":       ts,
	})
}

func getOne(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": "invalid id"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	row, err := selectOne(ctx, `SELECT id, actor, action, resource, success, metadata, ts FROM audit_log WHERE id=$1`, id)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeJSON(w, 404, map[string]string{"error": "not found"})
			return
		}
		log.Printf("ERROR %s: select id: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "db error"})
		return
	}
	writeJSON(w, 200, row)
}

func byActor(w http.ResponseWriter, r *http.Request) {
	actor := chi.URLParam(r, "actor")
	limit := parseLimit(r, 100)
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := selectMany(ctx,
		`SELECT id, actor, action, resource, success, metadata, ts FROM audit_log WHERE actor=$1 ORDER BY id DESC LIMIT $2`,
		actor, limit)
	if err != nil {
		log.Printf("ERROR %s: select actor: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "db error"})
		return
	}
	writeJSON(w, 200, rows)
}

func byResource(w http.ResponseWriter, r *http.Request) {
	resource := chi.URLParam(r, "resource")
	limit := parseLimit(r, 100)
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := selectMany(ctx,
		`SELECT id, actor, action, resource, success, metadata, ts FROM audit_log WHERE resource=$1 ORDER BY id DESC LIMIT $2`,
		resource, limit)
	if err != nil {
		log.Printf("ERROR %s: select resource: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "db error"})
		return
	}
	writeJSON(w, 200, rows)
}

func recent(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := selectMany(ctx,
		`SELECT id, actor, action, resource, success, metadata, ts FROM audit_log ORDER BY id DESC LIMIT 100`)
	if err != nil {
		log.Printf("ERROR %s: select recent: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "db error"})
		return
	}
	writeJSON(w, 200, rows)
}

func failures(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	msgs, err := rdb.XRevRangeN(ctx, "events:audit_failures", "+", "-", 50).Result()
	if err != nil {
		log.Printf("ERROR %s: xrevrange: %v", SERVICE, err)
		writeJSON(w, 502, map[string]string{"error": "redis error"})
		return
	}
	out := make([]map[string]interface{}, 0, len(msgs))
	for _, m := range msgs {
		entry := map[string]interface{}{"stream_id": m.ID}
		for k, v := range m.Values {
			entry[k] = v
		}
		out = append(out, entry)
	}
	writeJSON(w, 200, out)
}

func parseLimit(r *http.Request, dflt int) int {
	q := r.URL.Query().Get("limit")
	if q == "" {
		return dflt
	}
	n, err := strconv.Atoi(q)
	if err != nil || n <= 0 || n > 1000 {
		return dflt
	}
	return n
}

func selectOne(ctx context.Context, query string, args ...interface{}) (*AuditRow, error) {
	var row AuditRow
	var metaBytes []byte
	err := pg.QueryRow(ctx, query, args...).Scan(
		&row.ID, &row.Actor, &row.Action, &row.Resource, &row.Success, &metaBytes, &row.TS)
	if err != nil {
		return nil, err
	}
	if len(metaBytes) > 0 {
		_ = json.Unmarshal(metaBytes, &row.Metadata)
	}
	return &row, nil
}

func selectMany(ctx context.Context, query string, args ...interface{}) ([]AuditRow, error) {
	rs, err := pg.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rs.Close()
	out := make([]AuditRow, 0, 32)
	for rs.Next() {
		var row AuditRow
		var metaBytes []byte
		if err := rs.Scan(&row.ID, &row.Actor, &row.Action, &row.Resource, &row.Success, &metaBytes, &row.TS); err != nil {
			return nil, err
		}
		if len(metaBytes) > 0 {
			_ = json.Unmarshal(metaBytes, &row.Metadata)
		}
		out = append(out, row)
	}
	return out, rs.Err()
}
