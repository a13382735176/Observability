package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "tax-calculator"

var (
	rdb        *redis.Client
	httpClient *http.Client
	upstream   string
)

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

type taxReq struct {
	Region        string `json:"region"`
	SubtotalCents int64  `json:"subtotal_cents"`
}

type taxResp struct {
	Region     string `json:"region"`
	RateBp     int    `json:"rate_bp"`
	TaxCents   int64  `json:"tax_cents"`
	TotalCents int64  `json:"total_cents"`
}

type rateBody struct {
	RateBp int `json:"rate_bp"`
}

func rateKey(region string) string {
	return "tax_rate:" + region
}

func fetchRateUpstream(ctx context.Context, region string) (int, error) {
	url := fmt.Sprintf("%s/tax_rate?region=%s", upstream, region)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return 0, fmt.Errorf("upstream status %d", resp.StatusCode)
	}
	var rb rateBody
	if err := json.NewDecoder(resp.Body).Decode(&rb); err != nil {
		return 0, err
	}
	return rb.RateBp, nil
}

func getRate(ctx context.Context, region string) (int, bool, error) {
	rctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	v, err := rdb.Get(rctx, rateKey(region)).Result()
	if err == nil {
		if n, perr := strconv.Atoi(v); perr == nil {
			return n, true, nil
		}
	} else if err != redis.Nil {
		log.Printf("ERROR %s: redis get: %v", SERVICE, err)
	}
	ufetch, ucancel := context.WithTimeout(ctx, 2*time.Second)
	defer ucancel()
	rate, ferr := fetchRateUpstream(ufetch, region)
	if ferr != nil {
		log.Printf("ERROR %s: upstream: %v", SERVICE, ferr)
		return 0, false, ferr
	}
	sctx, scancel := context.WithTimeout(ctx, 2*time.Second)
	defer scancel()
	if err := rdb.Set(sctx, rateKey(region), strconv.Itoa(rate), time.Hour).Err(); err != nil {
		log.Printf("ERROR %s: redis set: %v", SERVICE, err)
	}
	return rate, false, nil
}

func handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": SERVICE})
}

func handleTax(c *gin.Context) {
	var req taxReq
	if err := c.BindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "bad json"})
		return
	}
	if req.Region == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "region required"})
		return
	}
	rate, _, err := getRate(c.Request.Context(), req.Region)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "rate lookup failed"})
		return
	}
	tax := req.SubtotalCents * int64(rate) / 10000
	c.JSON(http.StatusOK, taxResp{
		Region:     req.Region,
		RateBp:     rate,
		TaxCents:   tax,
		TotalCents: req.SubtotalCents + tax,
	})
}

func handleListRates(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	keys, err := rdb.Keys(ctx, "tax_rate:*").Result()
	if err != nil {
		log.Printf("ERROR %s: keys: %v", SERVICE, err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "cache error"})
		return
	}
	out := map[string]int{}
	for _, k := range keys {
		gctx, gcancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		v, gerr := rdb.Get(gctx, k).Result()
		gcancel()
		if gerr != nil {
			continue
		}
		if n, perr := strconv.Atoi(v); perr == nil {
			out[k[len("tax_rate:"):]] = n
		}
	}
	c.JSON(http.StatusOK, gin.H{"rates": out})
}

func handleRefreshRate(c *gin.Context) {
	region := c.Query("region")
	if region == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "region required"})
		return
	}
	dctx, dcancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	if err := rdb.Del(dctx, rateKey(region)).Err(); err != nil {
		log.Printf("ERROR %s: redis del: %v", SERVICE, err)
	}
	dcancel()
	rate, _, err := getRate(c.Request.Context(), region)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "rate refresh failed"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"region": region, "rate_bp": rate})
}

func handleDeleteRate(c *gin.Context) {
	region := c.Param("region")
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	n, err := rdb.Del(ctx, rateKey(region)).Result()
	if err != nil {
		log.Printf("ERROR %s: redis del: %v", SERVICE, err)
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "cache error"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"region": region, "removed": n})
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	host := getenv("REDIS_CACHE_HOST", "redis-cache")
	port := getenv("REDIS_CACHE_PORT", "6379")
	upstream = getenv("UPSTREAM_URL", "http://mock-upstream:8080")

	rdb = redis.NewClient(&redis.Options{
		Addr:         host + ":" + port,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})
	httpClient = &http.Client{Timeout: 2 * time.Second}

	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.GET("/healthz", handleHealth)
	r.POST("/tax", handleTax)
	r.GET("/rates", handleListRates)
	r.POST("/rates/refresh", handleRefreshRate)
	r.DELETE("/rates/:region", handleDeleteRate)

	log.Printf("INFO %s: listening on :8080", SERVICE)
	if err := r.Run("0.0.0.0:8080"); err != nil {
		log.Fatalf("ERROR %s: server: %v", SERVICE, err)
	}
}
