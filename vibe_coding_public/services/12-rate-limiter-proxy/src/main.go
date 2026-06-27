// 12-rate-limiter-proxy — fixed-window rate limiter that reverse-proxies
// /api/* to UPSTREAM_URL. Counter key per (client IP, minute) in redis-cache.
//
// Endpoints:
//
//	GET /healthz
//	ANY /api/...          — proxied to UPSTREAM_URL/... if under limit, else 429
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	limitPerMinute = 100
	windowSeconds  = 60
)

var (
	rdb         *redis.Client
	upstreamURL *url.URL
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.SplitN(xff, ",", 2)
		return strings.TrimSpace(parts[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"ok":true}`))
}

func handleAPI(w http.ResponseWriter, r *http.Request) {
	ip := clientIP(r)
	minute := time.Now().Unix() / int64(windowSeconds)
	key := fmt.Sprintf("rl:%s:%d", ip, minute)
	ctx, cancel := context.WithTimeout(r.Context(), 1*time.Second)
	defer cancel()

	count, err := rdb.Incr(ctx, key).Result()
	if err != nil {
		log.Printf("ERROR redis incr %s: %v", key, err)
		http.Error(w, fmt.Sprintf("rate-limiter: redis error: %v", err), http.StatusBadGateway)
		return
	}
	if count == 1 {
		_, _ = rdb.Expire(ctx, key, time.Duration(windowSeconds)*time.Second).Result()
	}
	if count > limitPerMinute {
		log.Printf("WARN ip=%s count=%d rate-limited", ip, count)
		http.Error(w, "rate limited", http.StatusTooManyRequests)
		return
	}

	// Reverse-proxy: rewrite /api/foo -> $UPSTREAM_URL/foo
	stripped := strings.TrimPrefix(r.URL.Path, "/api")
	if stripped == "" {
		stripped = "/"
	}
	target := *upstreamURL
	target.Path = strings.TrimRight(target.Path, "/") + stripped
	target.RawQuery = r.URL.RawQuery

	req, err := http.NewRequestWithContext(r.Context(), r.Method, target.String(), r.Body)
	if err != nil {
		log.Printf("ERROR build upstream req: %v", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	req.Header = r.Header.Clone()
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("ERROR upstream call %s: %v", target.String(), err)
		if errors.Is(err, context.DeadlineExceeded) {
			http.Error(w, "upstream timeout", http.StatusGatewayTimeout)
		} else {
			http.Error(w, fmt.Sprintf("upstream error: %v", err), http.StatusBadGateway)
		}
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		log.Printf("ERROR upstream %d %s", resp.StatusCode, target.String())
	}
	for k, vs := range resp.Header {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Println("rate-limiter-proxy starting")
	rdb = redis.NewClient(&redis.Options{
		Addr:         envOr("REDIS_CACHE_HOST", "redis-cache") + ":" + envOr("REDIS_CACHE_PORT", "6379"),
		DialTimeout:  1 * time.Second,
		ReadTimeout:  1 * time.Second,
		WriteTimeout: 1 * time.Second,
	})
	upstreamRaw := envOr("UPSTREAM_URL", "http://mock-upstream:8080")
	u, err := url.Parse(upstreamRaw)
	if err != nil {
		log.Fatalf("FATAL bad UPSTREAM_URL: %v", err)
	}
	upstreamURL = u
	log.Printf("limit=%d/min upstream=%s", limitPerMinute, upstreamURL)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.HandleFunc("/api/", handleAPI)
	mux.HandleFunc("/api", handleAPI)

	srv := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("FATAL listen: %v", err)
	}
}
