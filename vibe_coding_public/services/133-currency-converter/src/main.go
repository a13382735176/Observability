package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "currency-converter"

var (
	rdb         *redis.Client
	httpClient  = &http.Client{Timeout: 2 * time.Second}
	upstreamURL string
)

type RateResp struct {
	Rate float64 `json:"rate"`
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	redisHost := getenv("REDIS_HOST", "redis-cache")
	redisPort := getenv("REDIS_PORT", "6379")
	upstreamURL = getenv("UPSTREAM_URL", "http://mock-upstream:8080")

	rdb = redis.NewClient(&redis.Options{
		Addr:        redisHost + ":" + redisPort,
		DialTimeout: 2 * time.Second,
		ReadTimeout: 2 * time.Second,
	})

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(200, gin.H{"status": "ok", "service": SERVICE})
	})

	r.GET("/convert", convertHandler)
	r.POST("/rates/refresh", refreshHandler)
	r.GET("/rates", listRatesHandler)

	log.Printf("%s starting on :8080 upstream=%s", SERVICE, upstreamURL)
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

func convertHandler(c *gin.Context) {
	from := c.Query("from")
	to := c.Query("to")
	amountStr := c.Query("amount")
	if from == "" || to == "" || amountStr == "" {
		c.JSON(400, gin.H{"error": "from, to, amount required"})
		return
	}
	amount, err := strconv.ParseFloat(amountStr, 64)
	if err != nil {
		c.JSON(400, gin.H{"error": "invalid amount"})
		return
	}

	field := fmt.Sprintf("%s_%s", from, to)
	rate, ok := getCachedRate(field)
	if !ok {
		fetched, err := fetchUpstream(from, to)
		if err != nil {
			log.Printf("ERROR %s: upstream fetch %s->%s: %v", SERVICE, from, to, err)
			c.JSON(502, gin.H{"error": "upstream", "detail": err.Error()})
			return
		}
		rate = fetched
		cacheRate(field, rate)
	}

	c.JSON(200, gin.H{"from": from, "to": to, "amount": amount, "rate": rate, "result": amount * rate})
}

func getCachedRate(field string) (float64, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	v, err := rdb.HGet(ctx, "rates", field).Result()
	if err != nil {
		if err != redis.Nil {
			log.Printf("ERROR %s: redis HGET %s: %v", SERVICE, field, err)
		}
		return 0, false
	}
	rate, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return 0, false
	}
	return rate, true
}

func cacheRate(field string, rate float64) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := rdb.HSet(ctx, "rates", field, rate).Err(); err != nil {
		log.Printf("ERROR %s: redis HSET %s: %v", SERVICE, field, err)
		return
	}
	if err := rdb.Expire(ctx, "rates", 60*time.Second).Err(); err != nil {
		log.Printf("ERROR %s: redis EXPIRE rates: %v", SERVICE, err)
	}
}

func fetchUpstream(from, to string) (float64, error) {
	url := fmt.Sprintf("%s/rates?pair=%s%s", upstreamURL, from, to)
	resp, err := httpClient.Get(url)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		body, _ := io.ReadAll(resp.Body)
		return 0, fmt.Errorf("upstream status %d: %s", resp.StatusCode, string(body))
	}
	var rr RateResp
	if err := json.NewDecoder(resp.Body).Decode(&rr); err != nil {
		return 0, fmt.Errorf("decode: %w", err)
	}
	return rr.Rate, nil
}

func refreshHandler(c *gin.Context) {
	pairs := []struct{ From, To string }{
		{"USD", "EUR"},
		{"USD", "JPY"},
		{"EUR", "GBP"},
	}
	out := gin.H{}
	for _, p := range pairs {
		rate, err := fetchUpstream(p.From, p.To)
		if err != nil {
			log.Printf("ERROR %s: refresh %s->%s: %v", SERVICE, p.From, p.To, err)
			out[p.From+"_"+p.To] = gin.H{"error": err.Error()}
			continue
		}
		cacheRate(p.From+"_"+p.To, rate)
		out[p.From+"_"+p.To] = rate
	}
	c.JSON(200, gin.H{"refreshed": out})
}

func listRatesHandler(c *gin.Context) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	m, err := rdb.HGetAll(ctx, "rates").Result()
	if err != nil {
		log.Printf("ERROR %s: redis HGETALL: %v", SERVICE, err)
		c.JSON(502, gin.H{"error": err.Error()})
		return
	}
	c.JSON(200, gin.H{"rates": m})
}
