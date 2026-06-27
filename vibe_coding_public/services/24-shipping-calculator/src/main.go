package main

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/jackc/pgx/v5/stdlib"
)

const svc = "shipping-calculator"

var db *sql.DB

func main() {
	var err error
	db, err = sql.Open("pgx", getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"))
	if err != nil { log.Printf("ERROR %s: db open: %v", svc, err) }
	db.SetConnMaxLifetime(2 * time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil { log.Printf("ERROR %s: db ping: %v", svc, err) }
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS shipping_rates (
		id SERIAL PRIMARY KEY, zone TEXT NOT NULL,
		base_cents INT NOT NULL, per_gram_cents INT NOT NULL)`)
	if err != nil { log.Printf("ERROR %s: table init: %v", svc, err) } else {
		log.Printf("INFO %s: postgres ready", svc)
	}
	r := gin.Default()
	r.GET("/healthz", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok", "service": svc}) })
	r.GET("/rates", getRates)
	r.POST("/rates", addRate)
	r.POST("/quote", calcQuote)
	log.Printf("INFO %s: listening :8080", svc)
	r.Run(":8080")
}

func getRates(c *gin.Context) {
	rows, err := db.QueryContext(c.Request.Context(), "SELECT id,zone,base_cents,per_gram_cents FROM shipping_rates ORDER BY id")
	if err != nil { log.Printf("ERROR %s: getRates: %v", svc, err); c.JSON(500, gin.H{"error": "db error"}); return }
	defer rows.Close()
	type Rate struct{ ID int; Zone string; BaseCents int; PerGramCents int }
	var rates []gin.H
	for rows.Next() {
		var r Rate
		rows.Scan(&r.ID, &r.Zone, &r.BaseCents, &r.PerGramCents)
		rates = append(rates, gin.H{"id": r.ID, "zone": r.Zone, "base_cents": r.BaseCents, "per_gram_cents": r.PerGramCents})
	}
	if rates == nil { rates = []gin.H{} }
	c.JSON(200, rates)
}

func addRate(c *gin.Context) {
	var body struct {
		Zone         string `json:"zone"`
		BaseCents    int    `json:"base_cents"`
		PerGramCents int    `json:"per_gram_cents"`
	}
	if err := c.ShouldBindJSON(&body); err != nil { c.JSON(400, gin.H{"error": "bad request"}); return }
	var id int
	err := db.QueryRowContext(c.Request.Context(),
		"INSERT INTO shipping_rates(zone,base_cents,per_gram_cents) VALUES($1,$2,$3) RETURNING id",
		body.Zone, body.BaseCents, body.PerGramCents).Scan(&id)
	if err != nil { log.Printf("ERROR %s: addRate: %v", svc, err); c.JSON(500, gin.H{"error": "db error"}); return }
	c.JSON(201, gin.H{"id": id, "zone": body.Zone, "base_cents": body.BaseCents, "per_gram_cents": body.PerGramCents})
}

func calcQuote(c *gin.Context) {
	var body struct {
		OriginZip string `json:"origin_zip"`
		DestZip   string `json:"dest_zip"`
		WeightG   int    `json:"weight_g"`
	}
	if err := c.ShouldBindJSON(&body); err != nil { c.JSON(400, gin.H{"error": "bad request"}); return }
	var baseCents, perGramCents int
	err := db.QueryRowContext(c.Request.Context(),
		"SELECT base_cents,per_gram_cents FROM shipping_rates LIMIT 1").Scan(&baseCents, &perGramCents)
	if err == sql.ErrNoRows { c.JSON(404, gin.H{"error": "no rates configured"}); return }
	if err != nil { log.Printf("ERROR %s: calcQuote: %v", svc, err); c.JSON(500, gin.H{"error": "db error"}); return }
	total := baseCents + perGramCents*body.WeightG
	c.JSON(200, gin.H{"origin_zip": body.OriginZip, "dest_zip": body.DestZip, "weight_g": body.WeightG, "total_cents": total})
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
