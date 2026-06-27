package main

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "os"
    "strconv"
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
        log.Printf("ERROR location-share: redis connect: %v", err)
    }

    r := chi.NewRouter()
    r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, 200, map[string]string{"status":"ok","service":"location-share"})
    })
    r.Put("/location/{user_id}", handlePutLocation)
    r.Get("/location/{user_id}", handleGetLocation)
    r.Get("/nearby", handleNearby)

    log.Println("location-share listening on :8080")
    if err := http.ListenAndServe(":8080", r); err != nil {
        log.Fatalf("ERROR location-share: %v", err)
    }
}

type locReq struct {
    Lat  float64 `json:"lat"`
    Lng  float64 `json:"lng"`
    TtlS int     `json:"ttl_s"`
}

func handlePutLocation(w http.ResponseWriter, r *http.Request) {
    userID := chi.URLParam(r, "user_id")
    var req locReq
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        writeJSON(w, 400, map[string]string{"error":"bad request"})
        return
    }
    ttl := req.TtlS
    if ttl == 0 { ttl = 300 }
    pipe := rdb.Pipeline()
    pipe.GeoAdd(r.Context(), "locations", &redis.GeoLocation{
        Name: userID, Longitude: req.Lng, Latitude: req.Lat,
    })
    pipe.Expire(r.Context(), "locations", time.Duration(ttl)*time.Second)
    if _, err := pipe.Exec(r.Context()); err != nil {
        log.Printf("ERROR location-share: PUT location %s: %v", userID, err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    writeJSON(w, 200, map[string]any{"user_id":userID,"lat":req.Lat,"lng":req.Lng,"ttl_s":ttl})
}

func handleGetLocation(w http.ResponseWriter, r *http.Request) {
    userID := chi.URLParam(r, "user_id")
    pos, err := rdb.GeoPos(r.Context(), "locations", userID).Result()
    if err != nil || len(pos) == 0 || pos[0] == nil {
        writeJSON(w, 404, map[string]string{"error":"location not found"})
        return
    }
    writeJSON(w, 200, map[string]any{"user_id":userID,"lat":pos[0].Latitude,"lng":pos[0].Longitude})
}

func handleNearby(w http.ResponseWriter, r *http.Request) {
    latStr := r.URL.Query().Get("lat")
    lngStr := r.URL.Query().Get("lng")
    radStr := r.URL.Query().Get("radius_km")
    lat, _ := strconv.ParseFloat(latStr, 64)
    lng, _ := strconv.ParseFloat(lngStr, 64)
    radius, _ := strconv.ParseFloat(radStr, 64)
    if radius == 0 { radius = 1 }
    res, err := rdb.GeoRadius(r.Context(), "locations", lng, lat, &redis.GeoRadiusQuery{
        Radius: radius, Unit: "km", WithCoord: true, Count: 50,
    }).Result()
    if err != nil {
        log.Printf("ERROR location-share: nearby query: %v", err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    result := make([]map[string]any, 0, len(res))
    for _, loc := range res {
        result = append(result, map[string]any{"user_id":loc.Name,"lat":loc.Latitude,"lng":loc.Longitude})
    }
    writeJSON(w, 200, map[string]any{"lat":lat,"lng":lng,"radius_km":radius,"nearby":result})
}
