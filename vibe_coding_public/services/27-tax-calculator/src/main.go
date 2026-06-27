package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

const svc = "tax-calculator"

var db *sql.DB

func main() {
	var err error
	db, err = sql.Open("pgx", getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"))
	if err != nil { log.Printf("ERROR %s: db open: %v", svc, err) }
	db.SetConnMaxLifetime(2 * time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil { log.Printf("ERROR %s: db ping: %v", svc, err) }
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS tax_rates (
		id SERIAL PRIMARY KEY, state TEXT UNIQUE NOT NULL, rate_pct REAL NOT NULL)`)
	if err != nil { log.Printf("ERROR %s: table init: %v", svc, err) } else {
		log.Printf("INFO %s: postgres ready", svc)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "ok", "service": svc})
	})
	mux.HandleFunc("/rates", ratesHandler)
	mux.HandleFunc("/calculate", calcHandler)
	log.Printf("INFO %s: listening :8080", svc)
	log.Fatal(http.ListenAndServe(":8080", mux))
}

func ratesHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method == http.MethodGet {
		rows, err := db.QueryContext(r.Context(), "SELECT id,state,rate_pct FROM tax_rates ORDER BY state")
		if err != nil { log.Printf("ERROR %s: GET /rates: %v", svc, err); http.Error(w, `{"error":"db error"}`, 500); return }
		defer rows.Close()
		type Rate struct{ ID int; State string; RatePct float64 }
		var rates []map[string]interface{}
		for rows.Next() {
			var rt Rate; rows.Scan(&rt.ID, &rt.State, &rt.RatePct)
			rates = append(rates, map[string]interface{}{"id": rt.ID, "state": rt.State, "rate_pct": rt.RatePct})
		}
		if rates == nil { rates = []map[string]interface{}{} }
		json.NewEncoder(w).Encode(rates)
	} else if r.Method == http.MethodPost {
		var body struct{ State string `json:"state"`; RatePct float64 `json:"rate_pct"` }
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil { http.Error(w, `{"error":"bad request"}`, 400); return }
		var id int
		err := db.QueryRowContext(r.Context(),
			"INSERT INTO tax_rates(state,rate_pct) VALUES($1,$2) ON CONFLICT(state) DO UPDATE SET rate_pct=$2 RETURNING id",
			body.State, body.RatePct).Scan(&id)
		if err != nil { log.Printf("ERROR %s: POST /rates: %v", svc, err); http.Error(w, `{"error":"db error"}`, 500); return }
		w.WriteHeader(201)
		json.NewEncoder(w).Encode(map[string]interface{}{"id": id, "state": body.State, "rate_pct": body.RatePct})
	} else {
		http.Error(w, `{"error":"method not allowed"}`, 405)
	}
}

func calcHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost { http.Error(w, `{"error":"method not allowed"}`, 405); return }
	var body struct{ AmountCents int `json:"amount_cents"`; State string `json:"state"` }
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil { http.Error(w, `{"error":"bad request"}`, 400); return }
	var ratePct float64
	err := db.QueryRowContext(r.Context(), "SELECT rate_pct FROM tax_rates WHERE state=$1", body.State).Scan(&ratePct)
	if err == sql.ErrNoRows { http.Error(w, `{"error":"state not found"}`, 404); return }
	if err != nil { log.Printf("ERROR %s: /calculate: %v", svc, err); http.Error(w, `{"error":"db error"}`, 500); return }
	taxCents := int(float64(body.AmountCents) * ratePct / 100.0)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"amount_cents": body.AmountCents, "state": body.State,
		"rate_pct": ratePct, "tax_cents": taxCents, "total_cents": body.AmountCents + taxCents,
	})
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
