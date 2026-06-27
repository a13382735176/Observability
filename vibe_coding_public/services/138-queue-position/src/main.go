package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "queue-position"

var rdb *redis.Client

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	redisHost := getenv("REDIS_HOST", "redis-cache")
	redisPort := getenv("REDIS_PORT", "6379")

	rdb = redis.NewClient(&redis.Options{
		Addr:         redisHost + ":" + redisPort,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok", "service": SERVICE})
	})

	r.POST("/queue/join", joinHandler)
	r.GET("/queue/:queue_name/position/:user_id", positionHandler)
	r.POST("/queue/:queue_name/next", nextHandler)
	r.GET("/queue/:queue_name/length", lengthHandler)

	log.Printf("%s starting on :8080", SERVICE)
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

func key(name string) string { return "queue:" + name }

type joinReq struct {
	QueueName string `json:"queue_name"`
	UserID    string `json:"user_id"`
}

func joinHandler(c *gin.Context) {
	var body joinReq
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(400, gin.H{"error": "invalid body"})
		return
	}
	if body.QueueName == "" || body.UserID == "" {
		c.JSON(400, gin.H{"error": "queue_name, user_id required"})
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	length, err := rdb.RPush(ctx, key(body.QueueName), body.UserID).Result()
	if err != nil {
		log.Printf("ERROR %s: redis RPUSH %s: %v", SERVICE, body.QueueName, err)
		c.JSON(503, gin.H{"error": "internal error"})
		return
	}
	c.JSON(201, gin.H{
		"queue_name": body.QueueName,
		"user_id":    body.UserID,
		"position":   length - 1,
	})
}

func positionHandler(c *gin.Context) {
	name := c.Param("queue_name")
	userID := c.Param("user_id")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	pos, err := rdb.LPos(ctx, key(name), userID, redis.LPosArgs{}).Result()
	if err == redis.Nil {
		c.JSON(200, gin.H{"queue_name": name, "user_id": userID, "position": -1})
		return
	}
	if err != nil {
		log.Printf("ERROR %s: redis LPOS %s %s: %v", SERVICE, name, userID, err)
		c.JSON(503, gin.H{"error": "internal error"})
		return
	}
	c.JSON(200, gin.H{"queue_name": name, "user_id": userID, "position": pos})
}

func nextHandler(c *gin.Context) {
	name := c.Param("queue_name")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	v, err := rdb.LPop(ctx, key(name)).Result()
	if err == redis.Nil {
		c.JSON(200, gin.H{"queue_name": name, "user_id": nil, "empty": true})
		return
	}
	if err != nil {
		log.Printf("ERROR %s: redis LPOP %s: %v", SERVICE, name, err)
		c.JSON(503, gin.H{"error": "internal error"})
		return
	}
	c.JSON(200, gin.H{"queue_name": name, "user_id": v, "empty": false})
}

func lengthHandler(c *gin.Context) {
	name := c.Param("queue_name")
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	n, err := rdb.LLen(ctx, key(name)).Result()
	if err != nil {
		log.Printf("ERROR %s: redis LLEN %s: %v", SERVICE, name, err)
		c.JSON(503, gin.H{"error": "internal error"})
		return
	}
	c.JSON(200, gin.H{"queue_name": name, "length": n})
}
