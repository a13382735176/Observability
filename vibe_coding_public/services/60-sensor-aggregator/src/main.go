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

    "github.com/gorilla/mux"
    "github.com/redis/go-redis/v9"
)

var rcache *redis.Client
var rstream *redis.Client

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
    rcache = redis.NewClient(&redis.Options{
        Addr:         envOr("REDIS_CACHE_HOST","redis-cache") + ":" + envOr("REDIS_CACHE_PORT","6379"),
        DialTimeout:  2 * time.Second,
        ReadTimeout:  2 * time.Second,
        WriteTimeout: 2 * time.Second,
    })
    rstream = redis.NewClient(&redis.Options{
        Addr:         envOr("REDIS_STREAM_HOST","redis-stream") + ":" + envOr("REDIS_STREAM_PORT","6379"),
        DialTimeout:  2 * time.Second,
        ReadTimeout:  2 * time.Second,
        WriteTimeout: 2 * time.Second,
    })
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    if err := rcache.Ping(ctx).Err(); err != nil {
        log.Printf("ERROR sensor-aggregator: redis-cache connect: %v", err)
    }
    if err := rstream.Ping(ctx).Err(); err != nil {
        log.Printf("ERROR sensor-aggregator: redis-stream connect: %v", err)
    }

    r := mux.NewRouter()
    r.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
        writeJSON(w, 200, map[string]string{"status":"ok","service":"sensor-aggregator"})
    }).Methods("GET")
    r.HandleFunc("/readings", handleReadings).Methods("POST")
    r.HandleFunc("/aggregate/{device_id}", handleAggregate).Methods("GET")

    log.Println("sensor-aggregator listening on :8080")
    if err := http.ListenAndServe(":8080", r); err != nil {
        log.Fatalf("ERROR sensor-aggregator: %v", err)
    }
}

type reading struct {
    Metric string  `json:"metric"`
    Value  float64 `json:"value"`
}

type readingsReq struct {
    DeviceID string    `json:"device_id"`
    Readings []reading `json:"readings"`
}

func hourKey(deviceID, metric string) string {
    h := time.Now().UTC().Format("2006010215")
    return fmt.Sprintf("agg:%s:%s:%s", deviceID, metric, h)
}

func handleReadings(w http.ResponseWriter, r *http.Request) {
    var req readingsReq
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        writeJSON(w, 400, map[string]string{"error":"bad request"})
        return
    }
    pipe := rcache.Pipeline()
    for _, rd := range req.Readings {
        key := hourKey(req.DeviceID, rd.Metric)
        pipe.LPush(r.Context(), key, strconv.FormatFloat(rd.Value, 'f', 4, 64))
        pipe.Expire(r.Context(), key, 2*time.Hour)
    }
    if _, err := pipe.Exec(r.Context()); err != nil {
        log.Printf("ERROR sensor-aggregator: cache pipeline: %v", err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    // publish to stream
    fields := map[string]any{"event":"sensor.readings","device_id":req.DeviceID,"count":len(req.Readings)}
    b, _ := json.Marshal(fields)
    if err := rstream.XAdd(r.Context(), &redis.XAddArgs{
        Stream: "events:sensors",
        Values: map[string]any{"event":"sensor.readings","payload":string(b)},
    }).Err(); err != nil {
        log.Printf("ERROR sensor-aggregator: stream xadd: %v", err)
    }
    writeJSON(w, 201, map[string]any{"device_id":req.DeviceID,"readings_count":len(req.Readings),"status":"queued"})
}

func handleAggregate(w http.ResponseWriter, r *http.Request) {
    deviceID := mux.Vars(r)["device_id"]
    // get keys matching this device
    pattern := fmt.Sprintf("agg:%s:*", deviceID)
    keys, err := rcache.Keys(r.Context(), pattern).Result()
    if err != nil {
        log.Printf("ERROR sensor-aggregator: keys scan: %v", err)
        writeJSON(w, 500, map[string]string{"error":"internal error"})
        return
    }
    aggregates := map[string]any{}
    for _, key := range keys {
        vals, err := rcache.LRange(r.Context(), key, 0, -1).Result()
        if err != nil { continue }
        var sum, count float64
        for _, v := range vals {
            f, err := strconv.ParseFloat(v, 64)
            if err == nil { sum += f; count++ }
        }
        if count > 0 {
            parts := key
            _ = parts
            // extract metric from key agg:device:metric:hour
            metric := "unknown"
            if len(key) > len("agg:"+deviceID+":") {
                rest := key[len("agg:"+deviceID+":"):]
                // metric is everything up to last ":"
                for i := len(rest) - 1; i >= 0; i-- {
                    if rest[i] == ':' { metric = rest[:i]; break }
                }
            }
            aggregates[metric] = map[string]any{"avg":sum/count,"count":int(count),"sum":sum}
        }
    }
    writeJSON(w, 200, map[string]any{"device_id":deviceID,"hourly_averages":aggregates})
}
