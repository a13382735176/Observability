package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/redis/go-redis/v9"
)

const SERVICE = "dns-resolver-svc"

var (
	rdb         *redis.Client
	upstreamURL string
	httpClient  = &http.Client{Timeout: 2 * time.Second}
)

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

type upstreamResp struct {
	IPs []string `json:"ips"`
}

func fetchUpstream(ctx context.Context, domain string) ([]string, error) {
	url := upstreamURL + "/dns?domain=" + domain
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, errFromStatus(resp.StatusCode, body)
	}
	var u upstreamResp
	if err := json.Unmarshal(body, &u); err != nil {
		return nil, err
	}
	return u.IPs, nil
}

type httpErr struct{ msg string }

func (e *httpErr) Error() string { return e.msg }

func errFromStatus(code int, body []byte) error {
	return &httpErr{msg: "upstream status " + http.StatusText(code) + " body=" + string(body)}
}

func cacheKey(domain string) string { return "dns:" + domain }

func setCache(ctx context.Context, domain string, ips []string) error {
	k := cacheKey(domain)
	joined := strings.Join(ips, ",")
	if err := rdb.HSet(ctx, k, "ips", joined).Err(); err != nil {
		return err
	}
	return rdb.Expire(ctx, k, 300*time.Second).Err()
}

func getCache(ctx context.Context, domain string) ([]string, bool, error) {
	v, err := rdb.HGet(ctx, cacheKey(domain), "ips").Result()
	if err == redis.Nil {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	if v == "" {
		return []string{}, true, nil
	}
	return strings.Split(v, ","), true, nil
}

func handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": SERVICE})
}

func handleResolve(w http.ResponseWriter, r *http.Request) {
	domain := chi.URLParam(r, "domain")
	if domain == "" {
		writeJSON(w, 400, map[string]any{"error": "domain required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ips, ok, err := getCache(ctx, domain)
	if err != nil {
		log.Printf("ERROR %s: GET /resolve cache: %v", SERVICE, err)
	}
	if ok {
		writeJSON(w, 200, map[string]any{"domain": domain, "ips": ips, "source": "cache"})
		return
	}
	ips, err = fetchUpstream(ctx, domain)
	if err != nil {
		log.Printf("ERROR %s: GET /resolve upstream %s: %v", SERVICE, domain, err)
		writeJSON(w, 503, map[string]any{"error": "upstream error"})
		return
	}
	if err := setCache(ctx, domain, ips); err != nil {
		log.Printf("ERROR %s: GET /resolve set-cache: %v", SERVICE, err)
	}
	writeJSON(w, 200, map[string]any{"domain": domain, "ips": ips, "source": "upstream"})
}

type refreshReq struct {
	Domain string `json:"domain"`
}

func handleRefresh(w http.ResponseWriter, r *http.Request) {
	var body refreshReq
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Domain == "" {
		writeJSON(w, 400, map[string]any{"error": "domain required"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ips, err := fetchUpstream(ctx, body.Domain)
	if err != nil {
		log.Printf("ERROR %s: POST /resolve/refresh upstream %s: %v", SERVICE, body.Domain, err)
		writeJSON(w, 503, map[string]any{"error": "upstream error"})
		return
	}
	if err := setCache(ctx, body.Domain, ips); err != nil {
		log.Printf("ERROR %s: POST /resolve/refresh set-cache: %v", SERVICE, err)
		writeJSON(w, 503, map[string]any{"error": "cache error"})
		return
	}
	writeJSON(w, 200, map[string]any{"domain": body.Domain, "ips": ips, "source": "upstream"})
}

func handleCached(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var cursor uint64
	domains := []string{}
	for {
		keys, next, err := rdb.Scan(ctx, cursor, "dns:*", 100).Result()
		if err != nil {
			log.Printf("ERROR %s: GET /cached scan: %v", SERVICE, err)
			writeJSON(w, 503, map[string]any{"error": "cache error"})
			return
		}
		for _, k := range keys {
			domains = append(domains, strings.TrimPrefix(k, "dns:"))
		}
		cursor = next
		if cursor == 0 {
			break
		}
	}
	writeJSON(w, 200, map[string]any{"domains": domains, "count": len(domains)})
}

func handleClearCache(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	var cursor uint64
	deleted := 0
	for {
		keys, next, err := rdb.Scan(ctx, cursor, "dns:*", 100).Result()
		if err != nil {
			log.Printf("ERROR %s: DELETE /cache scan: %v", SERVICE, err)
			writeJSON(w, 503, map[string]any{"error": "cache error"})
			return
		}
		if len(keys) > 0 {
			n, err := rdb.Del(ctx, keys...).Result()
			if err != nil {
				log.Printf("ERROR %s: DELETE /cache del: %v", SERVICE, err)
				writeJSON(w, 503, map[string]any{"error": "cache error"})
				return
			}
			deleted += int(n)
		}
		cursor = next
		if cursor == 0 {
			break
		}
	}
	writeJSON(w, 200, map[string]any{"deleted": deleted})
}

func main() {
	cacheHost := envOr("REDIS_CACHE_HOST", "redis-cache")
	cachePort := envOr("REDIS_CACHE_PORT", "6379")
	upstreamURL = envOr("UPSTREAM_URL", "http://mock-upstream:8080")

	rdb = redis.NewClient(&redis.Options{
		Addr:         cacheHost + ":" + cachePort,
		DialTimeout:  2 * time.Second,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	})

	r := chi.NewRouter()
	r.Get("/healthz", handleHealth)
	r.Get("/resolve/{domain}", handleResolve)
	r.Post("/resolve/refresh", handleRefresh)
	r.Get("/cached", handleCached)
	r.Delete("/cache", handleClearCache)

	log.Printf("%s listening on :8080 upstream=%s redis=%s:%s", SERVICE, upstreamURL, cacheHost, cachePort)
	if err := http.ListenAndServe("0.0.0.0:8080", r); err != nil {
		log.Fatalf("ERROR %s: listen: %v", SERVICE, err)
	}
}
