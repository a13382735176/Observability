package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/redis/go-redis/v9"
	"github.com/jackc/pgx/v5/pgxpool"
)

var db *pgxpool.Pool
var rdb *redis.Client

func main() {
	pgDSN := os.Getenv("PG_DSN")
	if pgDSN == "" {
		pgDSN = "postgres://vibe:vibe@postgres:5432/vibe"
	}
	cacheHost := os.Getenv("REDIS_CACHE_HOST")
	if cacheHost == "" {
		cacheHost = "redis-cache"
	}

	ctx := context.Background()
	var err error
	db, err = pgxpool.New(ctx, pgDSN)
	if err != nil {
		log.Fatalf("credit-score: pg: %v", err)
	}
	_, err = db.Exec(ctx, `CREATE TABLE IF NOT EXISTS credit_scores(
		id serial PRIMARY KEY,
		user_id text UNIQUE,
		score int,
		computed_at timestamptz DEFAULT now()
	)`)
	if err != nil {
		log.Printf("credit-score: create table: %v", err)
	}

	rdb = redis.NewClient(&redis.Options{
		Addr:         cacheHost + ":6379",
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	e := echo.New()
	e.HideBanner = true
	e.GET("/healthz", healthz)
	e.GET("/score/:user_id", getScore)
	e.POST("/compute", compute)

	log.Println("credit-score listening on 8080")
	e.Logger.Fatal(e.Start("0.0.0.0:8080"))
}

func healthz(c echo.Context) error {
	return c.JSON(http.StatusOK, map[string]string{"status": "ok", "service": "credit-score"})
}

func getScore(c echo.Context) error {
	userID := c.Param("user_id")
	ctx, cancel := context.WithTimeout(c.Request().Context(), 2*time.Second)
	defer cancel()
	// try cache first
	cacheKey := "credit:" + userID
	val, err := rdb.Get(ctx, cacheKey).Result()
	if err == nil {
		return c.JSON(http.StatusOK, map[string]string{"user_id": userID, "score": val, "source": "cache"})
	}
	// fallback to db
	var score int
	err = db.QueryRow(ctx, "SELECT score FROM credit_scores WHERE user_id=$1", userID).Scan(&score)
	if err != nil {
		return c.JSON(http.StatusNotFound, map[string]string{"error": "not found"})
	}
	return c.JSON(http.StatusOK, map[string]int{"score": score})
}

type ComputeReq struct {
	UserID               string  `json:"user_id"`
	PaymentHistoryPct    float64 `json:"payment_history_pct"`
	CreditUtilizationPct float64 `json:"credit_utilization_pct"`
}

func compute(c echo.Context) error {
	var req ComputeReq
	if err := c.Bind(&req); err != nil {
		return c.JSON(http.StatusBadRequest, map[string]string{"error": "bad request"})
	}
	score := 300 + int(req.PaymentHistoryPct*3.5) + int((100-req.CreditUtilizationPct)*2)
	ctx, cancel := context.WithTimeout(c.Request().Context(), 2*time.Second)
	defer cancel()
	_, err := db.Exec(ctx,
		`INSERT INTO credit_scores(user_id, score) VALUES($1,$2)
		 ON CONFLICT(user_id) DO UPDATE SET score=EXCLUDED.score, computed_at=now()`,
		req.UserID, score)
	if err != nil {
		log.Printf("credit-score: pg: %v", err)
		return c.JSON(http.StatusServiceUnavailable, map[string]string{"error": "db error"})
	}
	cacheKey := "credit:" + req.UserID
	_ = rdb.Set(ctx, cacheKey, score, 5*time.Minute).Err()
	return c.JSON(http.StatusCreated, map[string]interface{}{"user_id": req.UserID, "score": score})
}
