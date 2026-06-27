package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "os"
    "strings"
    "time"

    "github.com/go-chi/chi/v5"
    "github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func envOr(k, def string) string {
    if v := os.Getenv(k); v != "" { return v }
    return def
}

func writeJSON(w http.ResponseWriter, code int, v any) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    _ = json.NewEncoder(w).Encode(v)
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
        log.Printf("ERROR like-counter: redis connect: %v", err)
    }

    r := chi.NewRouter()
    r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, 200, map[string]string{"status":"ok","service":"like-counter"})
    })
    r.Post("/like/{content_id}", handleLike)
    r.Delete("/like/{content_id}", handleUnlike)
    r.Get("/likes/{content_id}", handleGetLikes)

    log.Println("like-counter listening on :8080")
    if err := http.ListenAndServe(":8080", r); err != nil {
        log.Fatalf("ERROR like-counter: %v", err)
    }
}

func contentKey(id string) string { return "likes:" + id }

func handleLike(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "content_id")
    val, err := rdb.Incr(r.Context(), contentKey(id)).Result()
    if err != nil {
        log.Printf("ERROR like-counter: INCR likes:%s: %v", id, err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    writeJSON(w, 200, map[string]any{"content_id":id,"likes":val})
}

func handleUnlike(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "content_id")
    val, err := rdb.Decr(r.Context(), contentKey(id)).Result()
    if err != nil {
        log.Printf("ERROR like-counter: DECR likes:%s: %v", id, err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    if val < 0 {
        rdb.Set(r.Context(), contentKey(id), 0, 0)
        val = 0
    }
    writeJSON(w, 200, map[string]any{"content_id":id,"likes":val})
}

func handleGetLikes(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "content_id")
    val, err := rdb.Get(r.Context(), contentKey(id)).Int64()
    if err == redis.Nil {
        writeJSON(w, 200, map[string]any{"content_id":id,"likes":0})
        return
    }
    if err != nil {
        log.Printf("ERROR like-counter: GET likes:%s: %v", id, err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    writeJSON(w, 200, map[string]any{"content_id":id,"likes":val})
}

var _ = fmt.Sprintf
var _ = strings.TrimPrefix
