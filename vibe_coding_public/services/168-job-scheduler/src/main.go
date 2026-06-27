package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "job-scheduler"

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
		log.Printf("ERROR job-scheduler: parse pg dsn: %v", err)
		os.Exit(1)
	}
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	cfg.MaxConns = 8

	pctx, pcancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer pcancel()
	pg, err = pgxpool.NewWithConfig(pctx, cfg)
	if err != nil {
		log.Printf("ERROR job-scheduler: pg connect: %v", err)
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
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id bigserial PRIMARY KEY,
            name text,
            payload jsonb DEFAULT '{}',
            run_at timestamptz,
            status text DEFAULT 'pending',
            result text,
            created_at timestamptz DEFAULT now(),
            completed_at timestamptz
        )`); err != nil {
		log.Printf("ERROR job-scheduler: schema init: %v", err)
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/healthz", healthz)
	r.POST("/jobs", createJob)
	r.POST("/jobs/run-due", runDue)
	r.GET("/jobs/:id", getJob)
	r.GET("/jobs", listJobs)
	r.PUT("/jobs/:id/complete", completeJob)

	log.Printf("job-scheduler: listening on 0.0.0.0:8080")
	if err := r.Run("0.0.0.0:8080"); err != nil {
		log.Printf("ERROR job-scheduler: %v", err)
		os.Exit(1)
	}
}

func healthz(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok", "service": SERVICE})
}

func createJob(c *gin.Context) {
	var body struct {
		Name     string          `json:"name"`
		Payload  json.RawMessage `json:"payload"`
		RunAtISO string          `json:"run_at_iso"`
	}
	if err := c.ShouldBindJSON(&body); err != nil || body.Name == "" || body.RunAtISO == "" {
		c.JSON(400, gin.H{"error": "name, run_at_iso required"})
		return
	}
	runAt, err := time.Parse(time.RFC3339, body.RunAtISO)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid run_at_iso, want RFC3339"})
		return
	}
	payload := body.Payload
	if len(payload) == 0 {
		payload = []byte("{}")
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	var id int64
	var createdAt time.Time
	if err := pg.QueryRow(ctx,
		`INSERT INTO scheduled_jobs(name, payload, run_at)
		 VALUES($1, $2::jsonb, $3)
		 RETURNING id, created_at`,
		body.Name, string(payload), runAt,
	).Scan(&id, &createdAt); err != nil {
		log.Printf("ERROR job-scheduler: insert: %v", err)
		c.JSON(502, gin.H{"error": "db error"})
		return
	}
	c.JSON(201, gin.H{
		"id":         id,
		"name":       body.Name,
		"run_at":     runAt,
		"status":     "pending",
		"created_at": createdAt,
	})
}

func runDue(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	rows, err := pg.Query(ctx,
		`SELECT id, name FROM scheduled_jobs
		 WHERE status='pending' AND run_at <= now()
		 ORDER BY run_at ASC
		 LIMIT 50`)
	if err != nil {
		log.Printf("ERROR job-scheduler: select due: %v", err)
		c.JSON(502, gin.H{"error": "db error"})
		return
	}
	type due struct {
		ID   int64
		Name string
	}
	dueList := []due{}
	for rows.Next() {
		var d due
		if err := rows.Scan(&d.ID, &d.Name); err != nil {
			log.Printf("ERROR job-scheduler: scan: %v", err)
			continue
		}
		dueList = append(dueList, d)
	}
	rows.Close()

	dispatched := 0
	for _, d := range dueList {
		uctx, ucancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		_, err := pg.Exec(uctx,
			`UPDATE scheduled_jobs SET status='dispatched' WHERE id=$1 AND status='pending'`, d.ID)
		ucancel()
		if err != nil {
			log.Printf("ERROR job-scheduler: dispatch update %d: %v", d.ID, err)
			continue
		}
		sctx, scancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		_, xerr := stream.XAdd(sctx, &redis.XAddArgs{
			Stream: "events:jobs",
			Values: map[string]any{
				"id":   strconv.FormatInt(d.ID, 10),
				"name": d.Name,
			},
		}).Result()
		scancel()
		if xerr != nil {
			log.Printf("ERROR job-scheduler: XADD events:jobs: %v", xerr)
		}
		dispatched++
	}
	c.JSON(200, gin.H{"dispatched": dispatched})
}

func getJob(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid id"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	var (
		name        string
		payload     []byte
		runAt       time.Time
		status      string
		result      *string
		createdAt   time.Time
		completedAt *time.Time
	)
	if err := pg.QueryRow(ctx,
		`SELECT name, payload, run_at, status, result, created_at, completed_at
		 FROM scheduled_jobs WHERE id=$1`, id,
	).Scan(&name, &payload, &runAt, &status, &result, &createdAt, &completedAt); err != nil {
		if err == pgx.ErrNoRows {
			c.JSON(404, gin.H{"error": "not found"})
			return
		}
		log.Printf("ERROR job-scheduler: get %d: %v", id, err)
		c.JSON(502, gin.H{"error": "db error"})
		return
	}
	c.JSON(200, gin.H{
		"id":           id,
		"name":         name,
		"payload":      json.RawMessage(payload),
		"run_at":       runAt,
		"status":       status,
		"result":       result,
		"created_at":   createdAt,
		"completed_at": completedAt,
	})
}

func listJobs(c *gin.Context) {
	status := c.Query("status")
	if status != "" && status != "pending" && status != "dispatched" && status != "completed" {
		c.JSON(400, gin.H{"error": "status must be pending|dispatched|completed"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	var rows pgx.Rows
	var err error
	if status == "" {
		rows, err = pg.Query(ctx,
			`SELECT id, name, run_at, status, created_at FROM scheduled_jobs
			 ORDER BY id DESC LIMIT 50`)
	} else {
		rows, err = pg.Query(ctx,
			`SELECT id, name, run_at, status, created_at FROM scheduled_jobs
			 WHERE status=$1 ORDER BY id DESC LIMIT 50`, status)
	}
	if err != nil {
		log.Printf("ERROR job-scheduler: list: %v", err)
		c.JSON(502, gin.H{"error": "db error"})
		return
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var (
			id        int64
			name      string
			runAt     time.Time
			st        string
			createdAt time.Time
		)
		if err := rows.Scan(&id, &name, &runAt, &st, &createdAt); err != nil {
			log.Printf("ERROR job-scheduler: scan: %v", err)
			continue
		}
		out = append(out, map[string]any{
			"id":         id,
			"name":       name,
			"run_at":     runAt,
			"status":     st,
			"created_at": createdAt,
		})
	}
	c.JSON(200, out)
}

func completeJob(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid id"})
		return
	}
	var body struct {
		Result string `json:"result"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(400, gin.H{"error": "result required"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	var name string
	if err := pg.QueryRow(ctx,
		`UPDATE scheduled_jobs
		 SET status='completed', result=$1, completed_at=now()
		 WHERE id=$2
		 RETURNING name`,
		body.Result, id,
	).Scan(&name); err != nil {
		if err == pgx.ErrNoRows {
			c.JSON(404, gin.H{"error": "not found"})
			return
		}
		log.Printf("ERROR job-scheduler: complete %d: %v", id, err)
		c.JSON(502, gin.H{"error": "db error"})
		return
	}
	sctx, scancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer scancel()
	if _, xerr := stream.XAdd(sctx, &redis.XAddArgs{
		Stream: "events:job_completed",
		Values: map[string]any{
			"id":     strconv.FormatInt(id, 10),
			"name":   name,
			"result": body.Result,
		},
	}).Result(); xerr != nil {
		log.Printf("ERROR job-scheduler: XADD events:job_completed: %v", xerr)
	}
	c.JSON(200, gin.H{
		"id":     id,
		"status": "completed",
		"result": body.Result,
	})
}
