// 02-cart-service — shopping cart HTTP API backed by Redis.
//
// Endpoints:
//
//	GET    /healthz
//	GET    /cart/{user_id}
//	POST   /cart/{user_id}/items    body: {"sku": "...", "qty": 1}
//	DELETE /cart/{user_id}
//
// Cart is a Redis HASH at key cart:<user_id>, fields = sku, values = qty.
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
	"time"

	"github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func newRedis() *redis.Client {
	host := envOr("REDIS_CACHE_HOST", "redis-cache")
	port := envOr("REDIS_CACHE_PORT", "6379")
	return redis.NewClient(&redis.Options{
		Addr:         host + ":" + port,
		DialTimeout:  1 * time.Second,
		ReadTimeout:  1 * time.Second,
		WriteTimeout: 1 * time.Second,
	})
}

type addItemReq struct {
	SKU string `json:"sku"`
	Qty int    `json:"qty"`
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, err error) {
	log.Printf("ERROR status=%d err=%v", code, err)
	writeJSON(w, code, map[string]string{"error": err.Error()})
}

func parseUserID(path, prefix string) (string, error) {
	rest := strings.TrimPrefix(path, prefix)
	rest = strings.TrimSuffix(rest, "/")
	if rest == "" || strings.Contains(rest, "/") && !strings.HasSuffix(rest, "/items") {
		return "", fmt.Errorf("bad user_id in path %q", path)
	}
	// Strip "/items" if present.
	if strings.HasSuffix(rest, "/items") {
		rest = strings.TrimSuffix(rest, "/items")
	}
	if rest == "" {
		return "", fmt.Errorf("empty user_id in path %q", path)
	}
	return rest, nil
}

func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]bool{"ok": true})
}

func handleCart(w http.ResponseWriter, r *http.Request) {
	uid, err := parseUserID(r.URL.Path, "/cart/")
	if err != nil {
		writeErr(w, 400, err)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	key := "cart:" + uid

	switch r.Method {
	case http.MethodGet:
		items, err := rdb.HGetAll(ctx, key).Result()
		if err != nil {
			writeErr(w, 502, fmt.Errorf("redis hgetall failed: %w", err))
			return
		}
		writeJSON(w, 200, map[string]any{"user_id": uid, "items": items})

	case http.MethodDelete:
		_, err := rdb.Del(ctx, key).Result()
		if err != nil {
			writeErr(w, 502, fmt.Errorf("redis del failed: %w", err))
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})

	case http.MethodPost:
		if !strings.HasSuffix(r.URL.Path, "/items") {
			writeErr(w, 404, errors.New("POST only allowed on /cart/{uid}/items"))
			return
		}
		var req addItemReq
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeErr(w, 400, fmt.Errorf("bad json: %w", err))
			return
		}
		if req.SKU == "" || req.Qty <= 0 {
			writeErr(w, 400, errors.New("sku required + qty>0"))
			return
		}
		_, err := rdb.HIncrBy(ctx, key, req.SKU, int64(req.Qty)).Result()
		if err != nil {
			writeErr(w, 502, fmt.Errorf("redis hincrby failed: %w", err))
			return
		}
		writeJSON(w, 200, map[string]bool{"ok": true})

	default:
		writeErr(w, 405, errors.New("method not allowed"))
	}
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("cart-service starting")
	rdb = newRedis()

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/cart/", handleCart)

	addr := ":8080"
	log.Println("listening on", addr)
	srv := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("FATAL listen: %v", err)
	}
}
