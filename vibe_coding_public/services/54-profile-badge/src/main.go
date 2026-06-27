package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/redis/go-redis/v9"
)

var rdb *redis.Client

func envOr(k, def string) string {
    if v := os.Getenv(k); v != "" { return v }
    return def
}

func badgeKey(userID string) string { return "badges:" + userID }

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
        log.Printf("ERROR profile-badge: redis connect: %v", err)
    }

    gin.SetMode(gin.ReleaseMode)
    r := gin.New()
    r.Use(gin.Recovery())

    r.GET("/healthz", func(c *gin.Context) {
        c.JSON(http.StatusOK, gin.H{"status":"ok","service":"profile-badge"})
    })
    r.POST("/badges/award", awardBadge)
    r.GET("/badges/:user_id", getBadges)
    r.DELETE("/badges/:user_id/:badge_id", removeBadge)

    log.Println("profile-badge listening on :8080")
    if err := r.Run(":8080"); err != nil {
        log.Fatalf("ERROR profile-badge: %v", err)
    }
}

type awardReq struct {
    UserID  string `json:"user_id"`
    BadgeID string `json:"badge_id"`
}

func awardBadge(c *gin.Context) {
    var req awardReq
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(400, gin.H{"error":"bad request"})
        return
    }
    if err := rdb.SAdd(c.Request.Context(), badgeKey(req.UserID), req.BadgeID).Err(); err != nil {
        log.Printf("ERROR profile-badge: SADD badges:%s: %v", req.UserID, err)
        c.JSON(500, gin.H{"error":"internal error"})
        return
    }
    c.JSON(200, gin.H{"user_id":req.UserID,"badge_id":req.BadgeID,"status":"awarded"})
}

func getBadges(c *gin.Context) {
    userID := c.Param("user_id")
    badges, err := rdb.SMembers(c.Request.Context(), badgeKey(userID)).Result()
    if err != nil {
        log.Printf("ERROR profile-badge: SMEMBERS badges:%s: %v", userID, err)
        c.JSON(500, gin.H{"error":"internal error"})
        return
    }
    c.JSON(200, gin.H{"user_id":userID,"badges":badges})
}

func removeBadge(c *gin.Context) {
    userID := c.Param("user_id")
    badgeID := c.Param("badge_id")
    if err := rdb.SRem(c.Request.Context(), badgeKey(userID), badgeID).Err(); err != nil {
        log.Printf("ERROR profile-badge: SREM badges:%s %s: %v", userID, badgeID, err)
        c.JSON(500, gin.H{"error":"internal error"})
        return
    }
    c.JSON(200, gin.H{"user_id":userID,"badge_id":badgeID,"status":"removed"})
}
