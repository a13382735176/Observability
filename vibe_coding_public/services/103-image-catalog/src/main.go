package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

var (
	db  *pgxpool.Pool
	rdb *redis.Client
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	ctx := context.Background()

	var err error
	db, err = pgxpool.New(ctx, envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"))
	if err != nil {
		log.Printf("ERROR image-catalog: pgxpool create: %v", err)
	} else {
		ctxT, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		if err = db.Ping(ctxT); err != nil {
			log.Printf("ERROR image-catalog: postgres ping: %v", err)
		} else {
			_, err = db.Exec(ctx, `CREATE TABLE IF NOT EXISTS images(
				id SERIAL PRIMARY KEY,
				filename TEXT NOT NULL,
				width INT NOT NULL,
				height INT NOT NULL,
				url TEXT NOT NULL,
				created_at TIMESTAMPTZ DEFAULT NOW()
			)`)
			if err != nil {
				log.Printf("ERROR image-catalog: table create: %v", err)
			} else {
				log.Println("image-catalog: postgres ready")
			}
		}
	}

	rdb = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	ctxR, cancelR := context.WithTimeout(ctx, 2*time.Second)
	defer cancelR()
	if err = rdb.Ping(ctxR).Err(); err != nil {
		log.Printf("ERROR image-catalog: redis ping: %v", err)
	} else {
		log.Println("image-catalog: redis-cache ready")
	}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "image-catalog"})
	})
	r.POST("/images", handleCreateImage)
	r.GET("/images/:id", handleGetImage)
	r.GET("/images", handleListImages)

	log.Println("image-catalog listening on :8080")
	if err := r.Run(":8080"); err != nil {
		log.Fatalf("ERROR image-catalog: %v", err)
	}
}

type Image struct {
	ID        int    `json:"id"`
	Filename  string `json:"filename"`
	Width     int    `json:"width"`
	Height    int    `json:"height"`
	URL       string `json:"url"`
	CreatedAt string `json:"created_at"`
}

func handleCreateImage(c *gin.Context) {
	var body struct {
		Filename string `json:"filename"`
		Width    int    `json:"width"`
		Height   int    `json:"height"`
		URL      string `json:"url"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid body"})
		return
	}
	row := db.QueryRow(c.Request.Context(),
		"INSERT INTO images(filename,width,height,url) VALUES($1,$2,$3,$4) RETURNING id,filename,width,height,url,created_at",
		body.Filename, body.Width, body.Height, body.URL)
	var img Image
	var ts time.Time
	if err := row.Scan(&img.ID, &img.Filename, &img.Width, &img.Height, &img.URL, &ts); err != nil {
		log.Printf("ERROR image-catalog: POST /images: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "postgres error"})
		return
	}
	img.CreatedAt = ts.Format(time.RFC3339)
	b, _ := json.Marshal(img)
	ctx2, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := rdb.Set(ctx2, "img:"+strconv.Itoa(img.ID), string(b), 5*time.Minute).Err(); err != nil {
		log.Printf("ERROR image-catalog: cache set: %v", err)
	}
	c.JSON(http.StatusCreated, img)
}

func handleGetImage(c *gin.Context) {
	id := c.Param("id")
	ctx2, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	cached, err := rdb.Get(ctx2, "img:"+id).Result()
	if err == nil {
		var img Image
		if json.Unmarshal([]byte(cached), &img) == nil {
			c.JSON(http.StatusOK, img)
			return
		}
	}
	row := db.QueryRow(c.Request.Context(),
		"SELECT id,filename,width,height,url,created_at FROM images WHERE id=$1", id)
	var img Image
	var ts time.Time
	if err := row.Scan(&img.ID, &img.Filename, &img.Width, &img.Height, &img.URL, &ts); err != nil {
		log.Printf("ERROR image-catalog: GET /images/%s: %v", id, err)
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	img.CreatedAt = ts.Format(time.RFC3339)
	c.JSON(http.StatusOK, img)
}

func handleListImages(c *gin.Context) {
	widthMinStr := c.Query("width_min")
	var rows interface{ Scan(...any) error }
	var query string
	var args []any
	if widthMinStr != "" {
		wm, _ := strconv.Atoi(widthMinStr)
		query = "SELECT id,filename,width,height,url,created_at FROM images WHERE width>=$1 ORDER BY id"
		args = []any{wm}
	} else {
		query = "SELECT id,filename,width,height,url,created_at FROM images ORDER BY id DESC LIMIT 50"
	}
	pgrows, err := db.Query(c.Request.Context(), query, args...)
	if err != nil {
		log.Printf("ERROR image-catalog: GET /images: %v", err)
		c.JSON(http.StatusBadGateway, gin.H{"error": "postgres error"})
		return
	}
	defer pgrows.Close()
	_ = rows
	result := []Image{}
	for pgrows.Next() {
		var img Image
		var ts time.Time
		if err := pgrows.Scan(&img.ID, &img.Filename, &img.Width, &img.Height, &img.URL, &ts); err != nil {
			continue
		}
		img.CreatedAt = ts.Format(time.RFC3339)
		result = append(result, img)
	}
	c.JSON(http.StatusOK, result)
}
