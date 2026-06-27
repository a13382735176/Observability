package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/jackc/pgx/v5/stdlib"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

const svc = "search-service"

var db *sql.DB

func main() {
	dsn := getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
	var err error
	db, err = sql.Open("pgx", dsn)
	if err != nil {
		log.Printf("ERROR %s: db open: %v", svc, err)
	}
	db.SetConnMaxLifetime(2 * time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err = db.PingContext(ctx); err != nil {
		log.Printf("ERROR %s: db ping: %v", svc, err)
	}
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS search_index (
		id SERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '')`)
	if err != nil {
		log.Printf("ERROR %s: table init: %v", svc, err)
	} else {
		log.Printf("INFO %s: postgres ready", svc)
	}
	_ = stdlib.OpenDB // keep import
	e := echo.New()
	e.Use(middleware.Logger())
	e.GET("/healthz", func(c echo.Context) error {
		return c.JSON(http.StatusOK, map[string]string{"status": "ok", "service": svc})
	})
	e.GET("/search", searchHandler)
	e.POST("/index", indexHandler)
	log.Printf("INFO %s: listening :8080", svc)
	e.Logger.Fatal(e.Start(":8080"))
}

func searchHandler(c echo.Context) error {
	q := c.QueryParam("q")
	rows, err := db.QueryContext(c.Request().Context(),
		"SELECT id,name,description FROM search_index WHERE name ILIKE $1 OR description ILIKE $1",
		fmt.Sprintf("%%%s%%", q))
	if err != nil {
		log.Printf("ERROR %s: search query: %v", svc, err)
		return c.JSON(500, map[string]string{"error": "db error"})
	}
	defer rows.Close()
	type Item struct {
		ID   int    `json:"id"`
		Name string `json:"name"`
		Desc string `json:"description"`
	}
	var results []Item
	for rows.Next() {
		var it Item
		if err := rows.Scan(&it.ID, &it.Name, &it.Desc); err != nil {
			log.Printf("ERROR %s: scan: %v", svc, err)
		} else {
			results = append(results, it)
		}
	}
	if results == nil { results = []Item{} }
	return c.JSON(200, results)
}

func indexHandler(c echo.Context) error {
	var body struct {
		Name        string `json:"name"`
		Description string `json:"description"`
	}
	if err := c.Bind(&body); err != nil {
		return c.JSON(400, map[string]string{"error": "bad request"})
	}
	var id int
	err := db.QueryRowContext(c.Request().Context(),
		"INSERT INTO search_index(name,description) VALUES($1,$2) RETURNING id",
		body.Name, body.Description).Scan(&id)
	if err != nil {
		log.Printf("ERROR %s: index insert: %v", svc, err)
		return c.JSON(500, map[string]string{"error": "db error"})
	}
	return c.JSON(201, map[string]interface{}{"id": id, "name": body.Name})
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
