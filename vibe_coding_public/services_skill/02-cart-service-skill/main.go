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

	"github.com/go-redis/redis/v8"
	"github.com/gorilla/mux"
)

var (
	redisClient *redis.Client
)

func main() {
	addr := ":8080"
	redisURL := getenv("REDIS_CACHE_URL", "redis://redis-cache:6379/0")
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("[startup] failed to parse redis url: %v", err)
	}
	redisClient = redis.NewClient(opt)
	if err := pingRedis(); err != nil {
		log.Fatalf("[startup] redis unavailable: %v", err)
	}
	log.Printf("[startup] service starting on %s", addr)

	r := mux.NewRouter()
	r.HandleFunc("/healthz", healthzHandler).Methods("GET")
	r.HandleFunc("/cart/{uid}", getCartHandler).Methods("GET")
	r.HandleFunc("/cart/{uid}/items", addItemHandler).Methods("POST")
	r.HandleFunc("/cart/{uid}", clearCartHandler).Methods("DELETE")

	h := loggingMiddleware(r)
	h = recoverMiddleware(h)

	srv := &http.Server{
		Addr:    addr,
		Handler: h,
	}
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("[fatal] server error: %v", err)
	}
}

func getenv(key, def string) string {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	return v
}

func pingRedis() error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	return redisClient.Ping(ctx).Err()
}

func healthzHandler(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 1*time.Second)
	defer cancel()
	err := redisClient.Ping(ctx).Err()
	if err != nil {
		log.Printf("[healthz] redis ping failed: %v", err)
		w.WriteHeader(http.StatusServiceUnavailable)
		w.Write([]byte("unhealthy"))
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}

type CartItem struct {
	SKU string `json:"sku"`
	Qty int    `json:"qty"`
}

type Cart struct {
	Items []CartItem `json:"items"`
}

func getCartHandler(w http.ResponseWriter, r *http.Request) {
	uid := mux.Vars(r)["uid"]
	cartKey := fmt.Sprintf("cart:%s", uid)
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	m, err := redisClient.HGetAll(ctx, cartKey).Result()
	if err != nil {
		log.Printf("[cart.get] redis error: %v", err)
		http.Error(w, "cart unavailable", http.StatusInternalServerError)
		return
	}
	items := make([]CartItem, 0, len(m))
	for sku, qtyStr := range m {
		qty, err := strconv.Atoi(qtyStr)
		if err != nil {
			log.Printf("[cart.get] invalid qty for sku %s: %v", sku, err)
			continue
		}
		items = append(items, CartItem{SKU: sku, Qty: qty})
	}
	resp := Cart{Items: items}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func addItemHandler(w http.ResponseWriter, r *http.Request) {
	uid := mux.Vars(r)["uid"]
	cartKey := fmt.Sprintf("cart:%s", uid)
	var req CartItem
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		log.Printf("[cart.add] bad request: %v", err)
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	if req.SKU == "" || req.Qty <= 0 {
		log.Printf("[cart.add] invalid sku or qty: %+v", req)
		http.Error(w, "invalid sku or qty", http.StatusBadRequest)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	_, err := redisClient.HIncrBy(ctx, cartKey, req.SKU, int64(req.Qty)).Result()
	if err != nil {
		log.Printf("[cart.add] redis error: %v", err)
		http.Error(w, "cart unavailable", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func clearCartHandler(w http.ResponseWriter, r *http.Request) {
	uid := mux.Vars(r)["uid"]
	cartKey := fmt.Sprintf("cart:%s", uid)
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	_, err := redisClient.Del(ctx, cartKey).Result()
	if err != nil {
		log.Printf("[cart.clear] redis error: %v", err)
		http.Error(w, "cart unavailable", http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// loggingMiddleware logs request method, path, status, and latency.
func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sw := &statusWriter{ResponseWriter: w, status: 200}
		start := time.Now()
		next.ServeHTTP(sw, r)
		dur := time.Since(start)
		log.Printf("[access] %s %s %d %s", r.Method, r.URL.Path, sw.status, dur)
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}

// recoverMiddleware logs panics and returns 500.
func recoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("[panic] %v", rec)
				http.Error(w, "internal error", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}
