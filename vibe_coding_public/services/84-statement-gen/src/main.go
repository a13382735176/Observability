package main

import (
	"context"
	"log"
	"os"
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5/pgxpool"
)

var db *pgxpool.Pool

func main() {
	pgDSN := os.Getenv("PG_DSN")
	if pgDSN == "" {
		pgDSN = "postgres://vibe:vibe@postgres:5432/vibe"
	}
	ctx := context.Background()
	cfg, err := pgxpool.ParseConfig(pgDSN)
	if err != nil {
		log.Fatalf("ERROR statement-gen: pg config: %v", err)
	}
	cfg.ConnConfig.ConnectTimeout = 2 * time.Second
	db, err = pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		log.Fatalf("ERROR statement-gen: pg connect: %v", err)
	}
	_, err = db.Exec(ctx, `CREATE TABLE IF NOT EXISTS statements(
		id serial PRIMARY KEY,
		account_id text,
		from_date date,
		to_date date,
		net_cents bigint DEFAULT 0,
		generated_at timestamptz DEFAULT now()
	)`)
	if err != nil {
		log.Printf("ERROR statement-gen: create table: %v", err)
	}
	app := fiber.New(fiber.Config{DisableStartupMessage: true})
	app.Get("/healthz", healthz)
	app.Post("/generate", generate)
	app.Get("/statements/:account_id", getByAccount)
	app.Get("/statement/:id", getByID)
	log.Println("statement-gen listening on 8080")
	log.Fatal(app.Listen("0.0.0.0:8080"))
}

func healthz(c *fiber.Ctx) error {
	return c.JSON(fiber.Map{"status": "ok", "service": "statement-gen"})
}

type GenerateReq struct {
	AccountID string `json:"account_id"`
	FromDate  string `json:"from_date"`
	ToDate    string `json:"to_date"`
}

func generate(c *fiber.Ctx) error {
	var req GenerateReq
	if err := c.BodyParser(&req); err != nil {
		return c.Status(400).JSON(fiber.Map{"error": "bad request"})
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	var id int
	err := db.QueryRow(ctx,
		"INSERT INTO statements(account_id,from_date,to_date) VALUES($1,$2::date,$3::date) RETURNING id",
		req.AccountID, req.FromDate, req.ToDate,
	).Scan(&id)
	if err != nil {
		log.Printf("ERROR statement-gen: %v", err)
		return c.Status(503).JSON(fiber.Map{"error": "db error"})
	}
	return c.Status(201).JSON(fiber.Map{"id": id, "account_id": req.AccountID})
}

func getByAccount(c *fiber.Ctx) error {
	accountID := c.Params("account_id")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	rows, err := db.Query(ctx,
		"SELECT id,account_id,from_date::text,to_date::text,net_cents,generated_at::text FROM statements WHERE account_id=$1",
		accountID)
	if err != nil {
		log.Printf("ERROR statement-gen: %v", err)
		return c.Status(503).JSON(fiber.Map{"error": "db error"})
	}
	defer rows.Close()
	var result []fiber.Map
	for rows.Next() {
		var id int
		var accID, fromDate, toDate, genAt string
		var net int64
		if err := rows.Scan(&id, &accID, &fromDate, &toDate, &net, &genAt); err != nil {
			log.Printf("ERROR statement-gen: %v", err)
			continue
		}
		result = append(result, fiber.Map{"id": id, "account_id": accID, "from_date": fromDate, "to_date": toDate, "net_cents": net, "generated_at": genAt})
	}
	if result == nil {
		result = []fiber.Map{}
	}
	return c.JSON(result)
}

func getByID(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.Atoi(idStr)
	if err != nil {
		return c.Status(400).JSON(fiber.Map{"error": "invalid id"})
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	var accID, fromDate, toDate, genAt string
	var net int64
	err = db.QueryRow(ctx,
		"SELECT account_id,from_date::text,to_date::text,net_cents,generated_at::text FROM statements WHERE id=$1", id,
	).Scan(&accID, &fromDate, &toDate, &net, &genAt)
	if err != nil {
		return c.Status(404).JSON(fiber.Map{"error": "not found"})
	}
	return c.JSON(fiber.Map{"id": id, "account_id": accID, "from_date": fromDate, "to_date": toDate, "net_cents": net, "generated_at": genAt})
}
