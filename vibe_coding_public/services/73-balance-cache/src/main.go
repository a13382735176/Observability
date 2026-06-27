package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func main() {
	cacheHost := os.Getenv("REDIS_CACHE_HOST")
	if cacheHost == "" {
		cacheHost = "redis-cache"
	}
	rdb = redis.NewClient(&redis.Options{
		Addr:         cacheHost + ":6379",
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", healthz)
	r.GET("/balance/:account_id", getBalance)
	r.PUT("/balance/:account_id", putBalance)
	r.POST("/invalidate/:account_id", invalidate)

	log.Println("balance-cache listening on 8080")
	r.Run("0.0.0.0:8080")
}

func healthz(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "balance-cache"})
}

func getBalance(c *gin.Context) {
	acctID := c.Param("account_id")
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	val, err := rdb.HGet(ctx, "balances", acctID).Result()
	if err == redis.Nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
		return
	}
	if err != nil {
		log.Printf("balance-cache: redis: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "redis error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"account_id": acctID, "amount_cents": val})
}

func putBalance(c *gin.Context) {
	acctID := c.Param("account_id")
	var body struct {
		AmountCents int64 `json:"amount_cents"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bad request"})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	err := rdb.HSet(ctx, "balances", acctID, body.AmountCents).Err()
	if err != nil {
		log.Printf("balance-cache: redis: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "redis error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func invalidate(c *gin.Context) {
	acctID := c.Param("account_id")
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	err := rdb.HDel(ctx, "balances", acctID).Err()
	if err != nil {
		log.Printf("balance-cache: redis: %v", err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "redis error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
