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

func envOr(k, def string) string {
    if v := os.Getenv(k); v != "" { return v }
    return def
}

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
        log.Printf("ERROR media-cdn-proxy: redis connect: %v", err)
    }

    gin.SetMode(gin.ReleaseMode)
    r := gin.New()
    r.Use(gin.Recovery())

    r.GET("/healthz", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{"status":"ok","service":"media-cdn-proxy"})
    })
    r.GET("/media/:media_id", getMedia)
    r.PUT("/media/:media_id/meta", putMediaMeta)

    log.Println("media-cdn-proxy listening on :8080")
    if err := r.Run(":8080"); err != nil {
        log.Fatalf("ERROR media-cdn-proxy: %v", err)
    }
}

func mediaKey(id string) string { return "media:" + id }

func getMedia(c *gin.Context) {
    id := c.Param("media_id")
    data, err := rdb.HGetAll(c.Request.Context(), mediaKey(id)).Result()
    if err != nil {
        log.Printf("ERROR media-cdn-proxy: GET media %s: %v", id, err)
        c.JSON(500, gin.H{"error":"internal error"})
        return
    }
    if len(data) == 0 {
        // mock URL
        data = map[string]string{"url": "https://mock-cdn.example.com/" + id, "size_bytes": "0"}
    }
    c.JSON(200, gin.H{"media_id":id,"url":data["url"],"size_bytes":data["size_bytes"],"cached":len(data) > 0})
}

type metaReq struct {
    URL       string `json:"url"`
    SizeBytes string `json:"size_bytes"`
}

func putMediaMeta(c *gin.Context) {
    id := c.Param("media_id")
    var req metaReq
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(400, gin.H{"error":"bad request"})
        return
    }
    if err := rdb.HSet(c.Request.Context(), mediaKey(id), "url", req.URL, "size_bytes", req.SizeBytes).Err(); err != nil {
        log.Printf("ERROR media-cdn-proxy: PUT meta %s: %v", id, err)
        c.JSON(500, gin.H{"error":"internal error"})
        return
    }
    c.JSON(200, gin.H{"media_id":id,"url":req.URL,"size_bytes":req.SizeBytes,"cached":true})
}
