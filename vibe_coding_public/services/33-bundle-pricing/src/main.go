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

const svc = "bundle-pricing"

var (
	ctx = context.Background()
	rdb *redis.Client
)

func main() {
	rdb = redis.NewClient(&redis.Options{
		Addr:        fmt.Sprintf("%s:%s", getenv("REDIS_CACHE_HOST", "redis-cache"), getenv("REDIS_CACHE_PORT", "6379")),
		DialTimeout: 2 * time.Second,
	})
	if _, err := rdb.Ping(ctx).Result(); err != nil {
		log.Printf("ERROR %s: redis ping: %v", svc, err)
	} else { log.Printf("INFO %s: redis connected", svc) }

	r := gin.Default()
	r.GET("/healthz", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok", "service": svc}) })
	r.GET("/bundles", getBundles)
	r.POST("/bundles", addBundle)
	r.GET("/bundles/:id/price", getBundlePrice)
	log.Printf("INFO %s: listening :8080", svc)
	r.Run(":8080")
}

var bundleSeq int64 = 0

func getBundles(c *gin.Context) {
	ids, err := rdb.SMembers(ctx, "bundles:all").Result()
	if err != nil { log.Printf("ERROR %s: smembers: %v", svc, err); c.JSON(500, gin.H{"error": "redis error"}); return }
	var bundles []map[string]interface{}
	for _, id := range ids {
		data, err := rdb.HGetAll(ctx, fmt.Sprintf("bundle:%s", id)).Result()
		if err != nil { log.Printf("ERROR %s: hgetall bundle:%s: %v", svc, id, err); continue }
		entry := map[string]interface{}{"id": id}
		for k, v := range data { entry[k] = v }
		bundles = append(bundles, entry)
	}
	if bundles == nil { bundles = []map[string]interface{}{} }
	c.JSON(200, bundles)
}

func addBundle(c *gin.Context) {
	var body struct {
		Name            string   `json:"name"`
		SKUs            []string `json:"skus"`
		BundlePriceCents int     `json:"bundle_price_cents"`
	}
	if err := c.ShouldBindJSON(&body); err != nil { c.JSON(400, gin.H{"error": "bad request"}); return }
	bundleSeq++
	id := fmt.Sprintf("%d", bundleSeq)
	key := fmt.Sprintf("bundle:%s", id)
	fields := map[string]interface{}{
		"name": body.Name, "bundle_price_cents": body.BundlePriceCents,
	}
	if err := rdb.HSet(ctx, key, fields).Err(); err != nil {
		log.Printf("ERROR %s: hset %s: %v", svc, key, err)
		c.JSON(500, gin.H{"error": "redis error"}); return
	}
	rdb.SAdd(ctx, "bundles:all", id)
	c.JSON(201, gin.H{"id": id, "name": body.Name, "bundle_price_cents": body.BundlePriceCents, "skus": body.SKUs})
}

func getBundlePrice(c *gin.Context) {
	id := c.Param("id")
	data, err := rdb.HGetAll(ctx, fmt.Sprintf("bundle:%s", id)).Result()
	if err != nil { log.Printf("ERROR %s: hgetall bundle:%s: %v", svc, id, err); c.JSON(500, gin.H{"error": "redis error"}); return }
	if len(data) == 0 { c.JSON(404, gin.H{"error": "bundle not found"}); return }
	price, _ := strconv.Atoi(data["bundle_price_cents"])
	c.JSON(200, gin.H{"id": id, "name": data["name"], "bundle_price_cents": price})
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" { return v }
	return def
}
