package com.vibe.story;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import javax.sql.DataSource;
import java.time.Instant;
import java.util.*;

@RestController
public class Controller {
    private static final Logger log = LoggerFactory.getLogger("story-service");
    private final DataSource ds;
    private final StringRedisTemplate redis;
    public Controller(DataSource ds, StringRedisTemplate redis) { this.ds = ds; this.redis = redis; }

    @GetMapping("/healthz")
    public Map<String,String> healthz() { return Map.of("status","ok","service","story-service"); }

    record StoryIn(String user_id, String media_url, Integer ttl_s) {}

    @PostMapping("/stories")
    public ResponseEntity<?> createStory(@RequestBody StoryIn req) {
        try {
            int ttl = req.ttl_s() != null ? req.ttl_s() : 86400;
            var expiresAt = Instant.now().plusSeconds(ttl).toString();
            try (var conn = ds.getConnection();
                 var ps = conn.prepareStatement("INSERT INTO stories(user_id,media_url,expires_at) VALUES(?,?,?::timestamptz) RETURNING id,user_id,media_url,expires_at")) {
                ps.setString(1, req.user_id()); ps.setString(2, req.media_url()); ps.setString(3, expiresAt);
                var rs = ps.executeQuery(); rs.next();
                var id = rs.getInt(1);
                // cache in ZSET score=expiry epoch
                redis.opsForZSet().add("stories:" + req.user_id(), String.valueOf(id), (double) Instant.now().plusSeconds(ttl).getEpochSecond());
                return ResponseEntity.status(201).body(Map.of("id",id,"user_id",req.user_id(),"media_url",req.media_url(),"expires_at",expiresAt));
            }
        } catch (Exception e) {
            log.error("story-service: POST /stories: {}", e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @GetMapping("/stories/{user_id}")
    public ResponseEntity<?> getStories(@PathVariable String user_id) {
        try {
            double now = (double) Instant.now().getEpochSecond();
            // prune expired from ZSET
            redis.opsForZSet().removeRangeByScore("stories:" + user_id, 0, now);
            var activeIds = redis.opsForZSet().range("stories:" + user_id, 0, -1);
            try (var conn = ds.getConnection();
                 var ps = conn.prepareStatement("SELECT id,user_id,media_url,expires_at FROM stories WHERE user_id=? AND expires_at > NOW() ORDER BY id")) {
                ps.setString(1, user_id);
                var rs = ps.executeQuery();
                var list = new ArrayList<Map<String,Object>>();
                while (rs.next()) list.add(Map.of("id",rs.getInt(1),"user_id",rs.getString(2),"media_url",rs.getString(3),"expires_at",rs.getString(4)));
                return ResponseEntity.ok(Map.of("user_id",user_id,"stories",list,"cached_count",activeIds != null ? activeIds.size() : 0));
            }
        } catch (Exception e) {
            log.error("story-service: GET /stories/{}: {}", user_id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }
}
