package main

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "os"
    "time"

    "github.com/gorilla/mux"
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
        log.Printf("ERROR hashtag-index: redis connect: %v", err)
    }

    r := mux.NewRouter()
    r.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, 200, map[string]string{"status":"ok","service":"hashtag-index"})
    }).Methods("GET")
    r.HandleFunc("/tag", handleTag).Methods("POST")
    r.HandleFunc("/trending", handleTrending).Methods("GET")
    r.HandleFunc("/tag/{tag}", handleGetTag).Methods("GET")

    log.Println("hashtag-index listening on :8080")
    if err := http.ListenAndServe(":8080", r); err != nil {
        log.Fatalf("ERROR hashtag-index: %v", err)
    }
}

type tagReq struct {
    Tag       string `json:"tag"`
    ContentID string `json:"content_id"`
}

func handleTag(w http.ResponseWriter, r *http.Request) {
    var req tagReq
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        writeJSON(w, 400, map[string]string{"error":"bad request"})
        return
    }
    pipe := rdb.Pipeline()
    pipe.ZIncrBy(r.Context(), "hashtags:count", 1, req.Tag)
    pipe.SAdd(r.Context(), "hashtag:"+req.Tag+":contents", req.ContentID)
    if _, err := pipe.Exec(r.Context()); err != nil {
        log.Printf("ERROR hashtag-index: tag pipeline: %v", err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    writeJSON(w, 200, map[string]string{"tag":req.Tag,"content_id":req.ContentID,"status":"indexed"})
}

func handleTrending(w http.ResponseWriter, r *http.Request) {
    items, err := rdb.ZRevRangeWithScores(r.Context(), "hashtags:count", 0, 9).Result()
    if err != nil {
        log.Printf("ERROR hashtag-index: trending: %v", err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    result := make([]map[string]any, 0, len(items))
    for _, z := range items {
        result = append(result, map[string]any{"tag":z.Member,"count":int(z.Score)})
    }
    writeJSON(w, 200, map[string]any{"trending":result})
}

func handleGetTag(w http.ResponseWriter, r *http.Request) {
    tag := mux.Vars(r)["tag"]
    contents, err := rdb.SMembers(r.Context(), "hashtag:"+tag+":contents").Result()
    if err != nil {
        log.Printf("ERROR hashtag-index: get tag %s: %v", tag, err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    count, _ := rdb.ZScore(r.Context(), "hashtags:count", tag).Result()
    writeJSON(w, 200, map[string]any{"tag":tag,"count":int(count),"contents":contents})
}
