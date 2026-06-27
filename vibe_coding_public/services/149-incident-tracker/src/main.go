package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "incident-tracker"

var (
	pgPool *pgxpool.Pool
	rdb    *redis.Client
)

type IncidentIn struct {
	Title            string `json:"title"`
	Severity         int    `json:"severity"`
	Description      string `json:"description"`
	AffectedService  string `json:"affected_service"`
}

type ResolveIn struct {
	Resolution string `json:"resolution"`
}

type Incident struct {
	ID              int64      `json:"id"`
	Title           string     `json:"title"`
	Severity        int        `json:"severity"`
	Description     string     `json:"description"`
	AffectedService string     `json:"affected_service"`
	Resolution      *string    `json:"resolution"`
	CreatedAt       time.Time  `json:"created_at"`
	ResolvedAt      *time.Time `json:"resolved_at"`
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	pgDSN := getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
	redisHost := getenv("REDIS_STREAM_HOST", "redis-stream")
	redisPort := getenv("REDIS_STREAM_PORT", "6379")

	cfg, err := pgxpool.ParseConfig(pgDSN)
	if err != nil {
		log.Fatalf("ERROR %s: parse PG_DSN: %v", SERVICE, err)
	}
	cfg.MaxConns = 4
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	pgPool, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Printf("ERROR %s: pgxpool: %v", SERVICE, err)
	}

	rdb = redis.NewClient(&redis.Options{
		Addr:        redisHost + ":" + redisPort,
		DialTimeout: 2 * time.Second,
		ReadTimeout: 2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	initDb()

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok", "service": SERVICE})
	})

	r.POST("/incidents", createHandler)
	r.GET("/incidents/active", listActiveHandler)
	r.GET("/incidents/by-service/:service_name", byServiceHandler)
	r.PUT("/incidents/:id/resolve", resolveHandler)
	r.GET("/incidents/:id", getHandler)

	log.Printf("%s listening on 0.0.0.0:8080", SERVICE)
	if err := r.Run("0.0.0.0:8080"); err != nil {
		log.Printf("ERROR %s: server: %v", SERVICE, err)
		os.Exit(1)
	}
}

func getenv(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func initDb() {
	if pgPool == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_, err := pgPool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS incidents(
			id BIGSERIAL PRIMARY KEY,
			title TEXT NOT NULL,
			severity INT NOT NULL,
			description TEXT,
			affected_service TEXT,
			resolution TEXT,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
			resolved_at TIMESTAMPTZ
		)
	`)
	if err != nil {
		log.Printf("ERROR %s: db init failed: %v", SERVICE, err)
		return
	}
	log.Printf("%s: db init ok", SERVICE)
}

func qctx() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 2*time.Second)
}

func scanIncident(row pgx.Row) (*Incident, error) {
	var inc Incident
	err := row.Scan(&inc.ID, &inc.Title, &inc.Severity, &inc.Description,
		&inc.AffectedService, &inc.Resolution, &inc.CreatedAt, &inc.ResolvedAt)
	if err != nil {
		return nil, err
	}
	return &inc, nil
}

func createHandler(c *gin.Context) {
	var in IncidentIn
	if err := c.ShouldBindJSON(&in); err != nil {
		c.JSON(400, gin.H{"error": "invalid body"})
		return
	}
	if in.Title == "" || in.Severity < 1 || in.Severity > 5 {
		c.JSON(400, gin.H{"error": "title required and severity must be 1..5"})
		return
	}
	ctx, cancel := qctx()
	defer cancel()
	row := pgPool.QueryRow(ctx,
		`INSERT INTO incidents(title,severity,description,affected_service)
		 VALUES($1,$2,$3,$4)
		 RETURNING id,title,severity,description,affected_service,resolution,created_at,resolved_at`,
		in.Title, in.Severity, in.Description, in.AffectedService)
	inc, err := scanIncident(row)
	if err != nil {
		log.Printf("ERROR %s: POST /incidents db: %v", SERVICE, err)
		c.JSON(503, gin.H{"error": "db error"})
		return
	}
	rctx, rcancel := qctx()
	defer rcancel()
	if err := rdb.XAdd(rctx, &redis.XAddArgs{
		Stream: "events:incidents",
		Values: map[string]interface{}{
			"id":       strconv.FormatInt(inc.ID, 10),
			"severity": strconv.Itoa(inc.Severity),
		},
	}).Err(); err != nil {
		log.Printf("ERROR %s: redis XADD events:incidents: %v", SERVICE, err)
	}
	c.JSON(201, inc)
}

func getHandler(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid id"})
		return
	}
	ctx, cancel := qctx()
	defer cancel()
	row := pgPool.QueryRow(ctx,
		`SELECT id,title,severity,description,affected_service,resolution,created_at,resolved_at
		 FROM incidents WHERE id=$1`, id)
	inc, err := scanIncident(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			c.JSON(404, gin.H{"error": "not found"})
			return
		}
		log.Printf("ERROR %s: GET /incidents/%d: %v", SERVICE, id, err)
		c.JSON(503, gin.H{"error": "db error"})
		return
	}
	c.JSON(200, inc)
}

func listActiveHandler(c *gin.Context) {
	ctx, cancel := qctx()
	defer cancel()
	rows, err := pgPool.Query(ctx,
		`SELECT id,title,severity,description,affected_service,resolution,created_at,resolved_at
		 FROM incidents WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 100`)
	if err != nil {
		log.Printf("ERROR %s: GET /incidents/active: %v", SERVICE, err)
		c.JSON(503, gin.H{"error": "db error"})
		return
	}
	defer rows.Close()
	out := []Incident{}
	for rows.Next() {
		inc, err := scanIncident(rows)
		if err != nil {
			log.Printf("ERROR %s: scan active: %v", SERVICE, err)
			continue
		}
		out = append(out, *inc)
	}
	c.JSON(200, out)
}

func byServiceHandler(c *gin.Context) {
	name := c.Param("service_name")
	ctx, cancel := qctx()
	defer cancel()
	rows, err := pgPool.Query(ctx,
		`SELECT id,title,severity,description,affected_service,resolution,created_at,resolved_at
		 FROM incidents WHERE affected_service=$1 ORDER BY id DESC LIMIT 100`, name)
	if err != nil {
		log.Printf("ERROR %s: GET /incidents/by-service/%s: %v", SERVICE, name, err)
		c.JSON(503, gin.H{"error": "db error"})
		return
	}
	defer rows.Close()
	out := []Incident{}
	for rows.Next() {
		inc, err := scanIncident(rows)
		if err != nil {
			log.Printf("ERROR %s: scan by-service: %v", SERVICE, err)
			continue
		}
		out = append(out, *inc)
	}
	c.JSON(200, out)
}

func resolveHandler(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid id"})
		return
	}
	var in ResolveIn
	if err := c.ShouldBindJSON(&in); err != nil {
		c.JSON(400, gin.H{"error": "invalid body"})
		return
	}
	ctx, cancel := qctx()
	defer cancel()
	row := pgPool.QueryRow(ctx,
		`UPDATE incidents SET resolved_at=now(), resolution=$2 WHERE id=$1
		 RETURNING id,title,severity,description,affected_service,resolution,created_at,resolved_at`,
		id, in.Resolution)
	inc, err := scanIncident(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			c.JSON(404, gin.H{"error": "not found"})
			return
		}
		log.Printf("ERROR %s: PUT /incidents/%d/resolve: %v", SERVICE, id, err)
		c.JSON(503, gin.H{"error": "db error"})
		return
	}
	rctx, rcancel := qctx()
	defer rcancel()
	if err := rdb.XAdd(rctx, &redis.XAddArgs{
		Stream: "events:incident_resolved",
		Values: map[string]interface{}{
			"id":       strconv.FormatInt(inc.ID, 10),
			"severity": strconv.Itoa(inc.Severity),
		},
	}).Err(); err != nil {
		log.Printf("ERROR %s: redis XADD events:incident_resolved: %v", SERVICE, err)
	}
	c.JSON(200, inc)
}

var _ = http.StatusOK
