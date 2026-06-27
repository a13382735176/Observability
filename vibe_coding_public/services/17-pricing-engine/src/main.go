package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

const svc = "pricing-engine"

var (
	ctx = context.Background()
	rdb *redis.Client
)

func main() {
	rdb = redis.NewClient(&redis.Options{
		Addr:         fmt.Sprintf("%s:%s", getenv("REDIS_CACHE_HOST", "redis-cache"), getenv("REDIS_CACHE_PORT", "6379")),
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	if _, err := rdb.Ping(ctx).Result(); err != nil {
		log.Printf("ERROR %s: redis ping: %v", svc, err)
	} else {
		log.Printf("INFO %s: redis connected", svc)
	}
	r := gin.Default()
	r.GET("/healthz", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok", "service": svc}) })
	r.GET("/price/:sku", getPrice)
	r.PUT("/price/:sku", putPrice)
	r.GET("/prices", getPrices)
	log.Printf("INFO %s: listening :8080", svc)
	r.Run(":8080")
}

func getPrice(c *gin.Context) {
	sku := c.Param("sku")
	val, err := rdb.HGet(ctx, "prices", sku).Result()
	if err == redis.Nil { c.JSON(http.StatusNotFound, gin.H{"error": "not found"}); return }
	if err != nil { log.Printf("ERROR %s: HGet prices %s: %v", svc, sku, err); c.JSON(500, gin.H{"error": "redis error"}); return }
	price, _ := strconv.Atoi(val)
	c.JSON(200, gin.H{"sku": sku, "price_cents": price})
}

func putPrice(c *gin.Context) {
	sku := c.Param("sku")
	var body struct{ Price int `json:"price"` }
	if err := c.ShouldBindJSON(&body); err != nil { c.JSON(400, gin.H{"error": "bad request"}); return }
	if err := rdb.HSet(ctx, "prices", sku, body.Price).Err(); err != nil {
		log.Printf("ERROR %s: HSet prices %s: %v", svc, sku, err)
		c.JSON(500, gin.H{"error": "redis error"}); return
	}
	c.JSON(200, gin.H{"sku": sku, "price_cents": body.Price})
}

func getPrices(c *gin.Context) {
	all, err := rdb.HGetAll(ctx, "prices").Result()
	if err != nil { log.Printf("ERROR %s: HGetAll prices: %v", svc, err); c.JSON(500, gin.H{"error": "redis error"}); return }
	result := map[string]int{}
	for k, v := range all {
		if p, e := strconv.Atoi(v); e == nil { result[k] = p }
	}
	c.JSON(200, result)
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
