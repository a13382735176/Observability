package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/redis/go-redis/v9"
)

const svc = "cart-recovery"

var (
	ctx    = context.Background()
	cache  *redis.Client
	stream *redis.Client
)

func main() {
	cache = redis.NewClient(&redis.Options{
		Addr:        fmt.Sprintf("%s:%s", getenv("REDIS_CACHE_HOST", "redis-cache"), getenv("REDIS_CACHE_PORT", "6379")),
		DialTimeout: 2 * time.Second,
	})
	stream = redis.NewClient(&redis.Options{
		Addr:        fmt.Sprintf("%s:%s", getenv("REDIS_STREAM_HOST", "redis-stream"), getenv("REDIS_STREAM_PORT", "6379")),
		DialTimeout: 2 * time.Second,
	})
	if _, err := cache.Ping(ctx).Result(); err != nil {
		log.Printf("ERROR %s: cache ping: %v", svc, err)
	} else { log.Printf("INFO %s: redis-cache connected", svc) }
	if _, err := stream.Ping(ctx).Result(); err != nil {
		log.Printf("ERROR %s: stream ping: %v", svc, err)
	} else { log.Printf("INFO %s: redis-stream connected", svc) }

	app := fiber.New()
	app.Get("/healthz", func(c *fiber.Ctx) error {
		return c.JSON(fiber.Map{"status": "ok", "service": svc})
	})
	app.Get("/abandoned-carts", getAbandoned)
	app.Post("/abandon", postAbandon)
	app.Delete("/carts/:user_id", deleteCart)

	log.Printf("INFO %s: listening :8080", svc)
	app.Listen(":8080")
}

func getAbandoned(c *fiber.Ctx) error {
	keys, err := cache.Keys(ctx, "cart:abandoned:*").Result()
	if err != nil { log.Printf("ERROR %s: keys: %v", svc, err); return c.Status(500).JSON(fiber.Map{"error": "redis error"}) }
	var carts []map[string]interface{}
	for _, k := range keys {
		data, err := cache.Get(ctx, k).Result()
		if err != nil { continue }
		var cart map[string]interface{}
		if json.Unmarshal([]byte(data), &cart) == nil {
			carts = append(carts, cart)
		}
	}
	if carts == nil { carts = []map[string]interface{}{} }
	return c.JSON(carts)
}

func postAbandon(c *fiber.Ctx) error {
	var body struct {
		UserID string        `json:"user_id"`
		Items  []interface{} `json:"items"`
	}
	if err := c.BodyParser(&body); err != nil { return c.Status(400).JSON(fiber.Map{"error": "bad request"}) }
	data, _ := json.Marshal(fiber.Map{"user_id": body.UserID, "items": body.Items})
	key := fmt.Sprintf("cart:abandoned:%s", body.UserID)
	if err := cache.SetEx(ctx, key, string(data), 24*time.Hour).Err(); err != nil {
		log.Printf("ERROR %s: cache setex: %v", svc, err)
		return c.Status(500).JSON(fiber.Map{"error": "redis error"})
	}
	if err := stream.XAdd(ctx, &redis.XAddArgs{
		Stream: "carts:abandoned",
		Values: map[string]interface{}{"user_id": body.UserID, "item_count": fmt.Sprintf("%d", len(body.Items))},
	}).Err(); err != nil {
		log.Printf("ERROR %s: stream xadd: %v", svc, err)
	}
	return c.Status(201).JSON(fiber.Map{"user_id": body.UserID, "items": body.Items})
}

func deleteCart(c *fiber.Ctx) error {
	userID := c.Params("user_id")
	key := fmt.Sprintf("cart:abandoned:%s", userID)
	if err := cache.Del(ctx, key).Err(); err != nil {
		log.Printf("ERROR %s: del %s: %v", svc, key, err)
		return c.Status(500).JSON(fiber.Map{"error": "redis error"})
	}
	return c.JSON(fiber.Map{"user_id": userID, "deleted": true})
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
