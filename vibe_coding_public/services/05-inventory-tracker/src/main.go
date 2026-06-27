// 05-inventory-tracker — consume order events from a Redis stream,
// decrement per-SKU stock in a Redis cache.
//
// Self-produces 1 fake order every 3s so there's always work.
//
// Endpoints:
//
//	GET /healthz
//	GET /stock/{sku}        — returns current stock for SKU (cache key inv:<sku>)
//	GET /stats
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
)

var (
	rdbStream *redis.Client
	rdbCache  *redis.Client

	consumed atomic.Int64
	errsCnt  atomic.Int64
)

const (
	streamKey = "orders:queue"
	group     = "inventory"
	consumer  = "i1"
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func mkRedis(host, port string) *redis.Client {
	return redis.NewClient(&redis.Options{
		Addr:         host + ":" + port,
		DialTimeout:  1 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 1 * time.Second,
	})
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func handleStock(w http.ResponseWriter, r *http.Request) {
	sku := strings.TrimPrefix(r.URL.Path, "/stock/")
	if sku == "" || strings.Contains(sku, "/") {
		writeJSON(w, 400, map[string]string{"error": "bad sku"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	v, err := rdbCache.Get(ctx, "inv:"+sku).Result()
	if err == redis.Nil {
		writeJSON(w, 404, map[string]string{"error": "no such sku"})
		return
	}
	if err != nil {
		log.Printf("ERROR redis get inv:%s: %v", sku, err)
		writeJSON(w, 502, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, 200, map[string]any{"sku": sku, "stock": v})
}

func handleStats(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]int64{
		"consumed": consumed.Load(),
		"errors":   errsCnt.Load(),
	})
}

func seedInventory(ctx context.Context) {
	for _, sku := range []string{"widget", "gadget", "sprocket", "doohickey"} {
		_, err := rdbCache.Set(ctx, "inv:"+sku, 1000, 0).Result()
		if err != nil {
			log.Printf("ERROR seeding inv:%s: %v", sku, err)
		}
	}
}

func producerLoop() {
	skus := []string{"widget", "gadget", "sprocket", "doohickey"}
	i := 0
	for {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		_, err := rdbStream.XAdd(ctx, &redis.XAddArgs{
			Stream: streamKey,
			Values: map[string]any{"sku": skus[i%len(skus)], "qty": "1"},
		}).Result()
		cancel()
		if err != nil {
			log.Printf("ERROR producer xadd: %v", err)
		}
		i++
		time.Sleep(3 * time.Second)
	}
}

func consumerLoop() {
	ctx0 := context.Background()
	if _, err := rdbStream.XGroupCreateMkStream(ctx0, streamKey, group, "$").Result(); err != nil {
		if !strings.Contains(err.Error(), "BUSYGROUP") {
			log.Printf("WARN xgroup create: %v", err)
		}
	}
	for {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		res, err := rdbStream.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    group,
			Consumer: consumer,
			Streams:  []string{streamKey, ">"},
			Count:    10,
			Block:    2 * time.Second,
		}).Result()
		cancel()
		if errors.Is(err, redis.Nil) {
			continue
		}
		if err != nil {
			log.Printf("ERROR xreadgroup: %v", err)
			errsCnt.Add(1)
			time.Sleep(500 * time.Millisecond)
			continue
		}
		for _, s := range res {
			for _, msg := range s.Messages {
				sku, _ := msg.Values["sku"].(string)
				qtyStr, _ := msg.Values["qty"].(string)
				qty := int64(1)
				fmt.Sscanf(qtyStr, "%d", &qty)
				ctx2, cancel2 := context.WithTimeout(context.Background(), 2*time.Second)
				_, err := rdbCache.DecrBy(ctx2, "inv:"+sku, qty).Result()
				if err != nil {
					log.Printf("ERROR cache decr inv:%s: %v", sku, err)
					errsCnt.Add(1)
					cancel2()
					continue
				}
				_, err = rdbStream.XAck(ctx2, streamKey, group, msg.ID).Result()
				cancel2()
				if err != nil {
					log.Printf("ERROR xack: %v", err)
					errsCnt.Add(1)
					continue
				}
				consumed.Add(1)
			}
		}
	}
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("inventory-tracker starting")

	cacheHost := envOr("REDIS_CACHE_HOST", "redis-cache")
	cachePort := envOr("REDIS_CACHE_PORT", "6379")
	streamHost := envOr("REDIS_STREAM_HOST", "redis-stream")
	streamPort := envOr("REDIS_STREAM_PORT", "6379")

	rdbCache = mkRedis(cacheHost, cachePort)
	rdbStream = mkRedis(streamHost, streamPort)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	seedInventory(ctx)
	cancel()

	go producerLoop()
	go consumerLoop()

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/stock/", handleStock)
	mux.HandleFunc("/stats", handleStats)

	log.Println("listening on :8080")
	srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("FATAL listen: %v", err)
	}
}
