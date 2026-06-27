package main

import (
    "context"
    "log"
    "os"
    "time"

    "github.com/gofiber/fiber/v2"
    "github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func envOr(k, def string) string {
    if v := os.Getenv(k); v != "" { return v }
    return def
}

func reactKey(contentID string) string { return "reactions:" + contentID }

func main() {
    rdb = redis.NewClient(&redis.Options{
        Addr:         envOr("REDIS_CACHE_HOST","redis-cache") + ":" + envOr("REDIS_CACHE_PORT","6379"),
        DialTimeout:  2 * time.Second,
        ReadTimeout:  2 * time.Second,
        WriteTimeout: 2 * time.Second,
    })
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    if err := rdb.Ping(ctx).Err(); err != nil {
        log.Printf("ERROR reaction-service: redis connect: %v", err)
    }

    app := fiber.New()

    app.Get("/healthz", func(c *fiber.Ctx) error {
        return c.JSON(fiber.Map{"status":"ok","service":"reaction-service"})
    })
    app.Post("/react", handleReact)
    app.Delete("/react/:content_id/:user_id", handleDeleteReact)
    app.Get("/reactions/:content_id", handleGetReactions)

    log.Println("reaction-service listening on :8080")
    if err := app.Listen(":8080"); err != nil {
        log.Fatalf("ERROR reaction-service: %v", err)
    }
}

type reactReq struct {
    ContentID string `json:"content_id"`
    UserID    string `json:"user_id"`
    Emoji     string `json:"emoji"`
}

func handleReact(c *fiber.Ctx) error {
    var req reactReq
    if err := c.BodyParser(&req); err != nil {
        return c.Status(400).JSON(fiber.Map{"error":"bad request"})
    }
    if err := rdb.HSet(c.Context(), reactKey(req.ContentID), req.UserID, req.Emoji).Err(); err != nil {
        log.Printf("ERROR reaction-service: HSET reactions:%s: %v", req.ContentID, err)
        return c.Status(500).JSON(fiber.Map{"error":"internal error"})
    }
    return c.JSON(fiber.Map{"content_id":req.ContentID,"user_id":req.UserID,"emoji":req.Emoji,"status":"set"})
}

func handleDeleteReact(c *fiber.Ctx) error {
    contentID := c.Params("content_id")
    userID := c.Params("user_id")
    if err := rdb.HDel(c.Context(), reactKey(contentID), userID).Err(); err != nil {
        log.Printf("ERROR reaction-service: HDEL reactions:%s %s: %v", contentID, userID, err)
        return c.Status(500).JSON(fiber.Map{"error":"internal error"})
    }
    return c.JSON(fiber.Map{"content_id":contentID,"user_id":userID,"status":"removed"})
}

func handleGetReactions(c *fiber.Ctx) error {
    contentID := c.Params("content_id")
    data, err := rdb.HGetAll(c.Context(), reactKey(contentID)).Result()
    if err != nil {
        log.Printf("ERROR reaction-service: HGETALL reactions:%s: %v", contentID, err)
        return c.Status(500).JSON(fiber.Map{"error":"internal error"})
    }
    return c.JSON(fiber.Map{"content_id":contentID,"reactions":data})
}
