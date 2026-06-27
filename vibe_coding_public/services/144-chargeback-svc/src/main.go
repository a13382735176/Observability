package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "chargeback-svc"

var (
	pg     *pgxpool.Pool
	stream *redis.Client
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

	stream = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_STREAM_HOST", "redis-stream") + ":" + envOr("REDIS_STREAM_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	initCtx, initCancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer initCancel()
	if _, err := pg.Exec(initCtx, `
        CREATE TABLE IF NOT EXISTS chargebacks (
            id bigserial PRIMARY KEY,
            payment_id int,
            reason text,
            amount_cents int,
            status text DEFAULT 'pending',
            resolution text,
            created_at timestamptz DEFAULT now(),
            resolved_at timestamptz
        )`); err != nil {
		log.Printf("ERROR %s: schema init: %v", SERVICE, err)
	}

	r := chi.NewRouter()
	r.Get("/healthz", healthz)
	r.Post("/chargebacks", createChargeback)
	r.Get("/chargebacks/pending", listPending)
	r.Get("/chargebacks/{payment_id}", getByPayment)
	r.Put("/chargebacks/{id}/resolve", resolveChargeback)

	log.Printf("%s: listening on :8080", SERVICE)
	if err := http.ListenAndServe(":8080", r); err != nil {
		log.Printf("ERROR %s: %v", SERVICE, err)
		os.Exit(1)
	}
}

func healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

func createChargeback(w http.ResponseWriter, r *http.Request) {
	var body struct {
		PaymentID    int    `json:"payment_id"`
		Reason       string `json:"reason"`
		AmountCents  int    `json:"amount_cents"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.PaymentID == 0 {
		http.Error(w, "payment_id, reason, amount_cents required", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	var id int64
	var createdAt time.Time
	if err := pg.QueryRow(ctx,
		`INSERT INTO chargebacks(payment_id, reason, amount_cents)
		 VALUES($1,$2,$3) RETURNING id, created_at`,
		body.PaymentID, body.Reason, body.AmountCents,
	).Scan(&id, &createdAt); err != nil {
		log.Printf("ERROR %s: insert: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}

	sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer scancel()
	if _, err := stream.XAdd(sctx, &redis.XAddArgs{
		Stream: "events:chargebacks",
		Values: map[string]any{
			"id":           strconv.FormatInt(id, 10),
			"payment_id":   strconv.Itoa(body.PaymentID),
			"amount_cents": strconv.Itoa(body.AmountCents),
		},
	}).Result(); err != nil {
		log.Printf("ERROR %s: XADD events:chargebacks: %v", SERVICE, err)
	}

	writeJSON(w, 200, map[string]any{
		"id":           id,
		"payment_id":   body.PaymentID,
		"reason":       body.Reason,
		"amount_cents": body.AmountCents,
		"status":       "pending",
		"created_at":   createdAt,
	})
}

func getByPayment(w http.ResponseWriter, r *http.Request) {
	pidStr := chi.URLParam(r, "payment_id")
	pid, err := strconv.Atoi(pidStr)
	if err != nil {
		http.Error(w, "invalid payment_id", 400)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	rows, err := pg.Query(ctx,
		`SELECT id, payment_id, reason, amount_cents, status, resolution, created_at, resolved_at
		 FROM chargebacks WHERE payment_id=$1 ORDER BY id ASC`, pid)
	if err != nil {
		log.Printf("ERROR %s: select: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}
	defer rows.Close()

	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var paymentID, amountCents int
		var reason, status string
		var resolution *string
		var createdAt time.Time
		var resolvedAt *time.Time
		if err := rows.Scan(&id, &paymentID, &reason, &amountCents, &status, &resolution, &createdAt, &resolvedAt); err != nil {
			log.Printf("ERROR %s: scan: %v", SERVICE, err)
			continue
		}
		out = append(out, map[string]any{
			"id":           id,
			"payment_id":   paymentID,
			"reason":       reason,
			"amount_cents": amountCents,
			"status":       status,
			"resolution":   resolution,
			"created_at":   createdAt,
			"resolved_at":  resolvedAt,
		})
	}
	writeJSON(w, 200, map[string]any{"payment_id": pid, "items": out})
}

func resolveChargeback(w http.ResponseWriter, r *http.Request) {
	idStr := chi.URLParam(r, "id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", 400)
		return
	}
	var body struct {
		Resolution string `json:"resolution"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "resolution required", 400)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var paymentID, amountCents int
	if err := pg.QueryRow(ctx,
		`UPDATE chargebacks
		 SET status='resolved', resolution=$1, resolved_at=now()
		 WHERE id=$2
		 RETURNING payment_id, amount_cents`,
		body.Resolution, id,
	).Scan(&paymentID, &amountCents); err != nil {
		log.Printf("ERROR %s: resolve: %v", SERVICE, err)
		http.Error(w, "db error or not found", 502)
		return
	}

	sctx, scancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer scancel()
	if _, err := stream.XAdd(sctx, &redis.XAddArgs{
		Stream: "events:chargeback_resolved",
		Values: map[string]any{
			"id":           strconv.FormatInt(id, 10),
			"payment_id":   strconv.Itoa(paymentID),
			"amount_cents": strconv.Itoa(amountCents),
			"resolution":   body.Resolution,
		},
	}).Result(); err != nil {
		log.Printf("ERROR %s: XADD events:chargeback_resolved: %v", SERVICE, err)
	}

	writeJSON(w, 200, map[string]any{
		"id":         id,
		"status":     "resolved",
		"resolution": body.Resolution,
	})
}

func listPending(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	rows, err := pg.Query(ctx,
		`SELECT id, payment_id, reason, amount_cents, status, resolution, created_at, resolved_at
		 FROM chargebacks WHERE status='pending' ORDER BY id ASC`)
	if err != nil {
		log.Printf("ERROR %s: list pending: %v", SERVICE, err)
		http.Error(w, "db error", 502)
		return
	}
	defer rows.Close()

	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var paymentID, amountCents int
		var reason, status string
		var resolution *string
		var createdAt time.Time
		var resolvedAt *time.Time
		if err := rows.Scan(&id, &paymentID, &reason, &amountCents, &status, &resolution, &createdAt, &resolvedAt); err != nil {
			log.Printf("ERROR %s: scan: %v", SERVICE, err)
			continue
		}
		out = append(out, map[string]any{
			"id":           id,
			"payment_id":   paymentID,
			"reason":       reason,
			"amount_cents": amountCents,
			"status":       status,
			"resolution":   resolution,
			"created_at":   createdAt,
			"resolved_at":  resolvedAt,
		})
	}
	writeJSON(w, 200, out)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
