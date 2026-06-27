package com.vibe.statuspage;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.time.Instant;
import java.util.*;

@RestController
public class StatusController {

    private static final String SERVICE = "status-page";
    private static final Logger log = LoggerFactory.getLogger(StatusController.class);
    private static final Set<String> VALID_STATES = Set.of("operational", "degraded", "down");

    @Autowired
    private StringRedisTemplate redis;

    private final ObjectMapper mapper = new ObjectMapper();

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/status")
    public ResponseEntity<?> postStatus(@RequestBody Map<String, Object> body) {
        Object compObj = body.get("component");
        Object stateObj = body.get("state");
        if (!(compObj instanceof String) || !(stateObj instanceof String)) {
            return ResponseEntity.badRequest().body(Map.of("error", "component and state required"));
        }
        String component = (String) compObj;
        String state = (String) stateObj;
        if (!VALID_STATES.contains(state)) {
            return ResponseEntity.badRequest().body(Map.of("error", "state must be operational|degraded|down"));
        }
        String message = body.get("message") instanceof String ? (String) body.get("message") : "";
        String key = "status:" + component;
        try {
            Map<String, String> fields = new HashMap<>();
            fields.put("state", state);
            fields.put("message", message);
            fields.put("ts", Instant.now().toString());
            redis.opsForHash().putAll(key, new HashMap<Object, Object>(fields));
            redis.expire(key, Duration.ofSeconds(600));
            return ResponseEntity.ok(Map.of(
                    "component", component, "state", state, "message", message, "ts", fields.get("ts")));
        } catch (Exception e) {
            log.error("status-page: POST /status redis: {}", e.toString());
            return ResponseEntity.status(503).body(Map.of("error", "redis error"));
        }
    }

    @GetMapping("/status/{component}")
    public ResponseEntity<?> getStatus(@PathVariable String component) {
        String key = "status:" + component;
        try {
            Map<Object, Object> all = redis.opsForHash().entries(key);
            if (all == null || all.isEmpty()) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            Map<String, String> out = new HashMap<>();
            out.put("component", component);
            all.forEach((k, v) -> out.put(String.valueOf(k), String.valueOf(v)));
            return ResponseEntity.ok(out);
        } catch (Exception e) {
            log.error("status-page: GET /status/{} redis: {}", component, e.toString());
            return ResponseEntity.status(503).body(Map.of("error", "redis error"));
        }
    }

    @GetMapping("/status")
    public ResponseEntity<?> listStatuses() {
        List<Map<String, String>> out = new ArrayList<>();
        try {
            ScanOptions opts = ScanOptions.scanOptions().match("status:*").count(100).build();
            try (Cursor<byte[]> cursor = Objects.requireNonNull(redis.getConnectionFactory()).getConnection().scan(opts)) {
                while (cursor.hasNext()) {
                    String key = new String(cursor.next());
                    String component = key.startsWith("status:") ? key.substring("status:".length()) : key;
                    Map<Object, Object> all = redis.opsForHash().entries(key);
                    Map<String, String> entry = new HashMap<>();
                    entry.put("component", component);
                    all.forEach((k, v) -> entry.put(String.valueOf(k), String.valueOf(v)));
                    out.add(entry);
                }
            }
            return ResponseEntity.ok(Map.of("statuses", out));
        } catch (Exception e) {
            log.error("status-page: GET /status redis SCAN: {}", e.toString());
            return ResponseEntity.status(503).body(Map.of("error", "redis error"));
        }
    }

    @PostMapping("/incident/banner")
    public ResponseEntity<?> postBanner(@RequestBody Map<String, Object> body) {
        Object msgObj = body.get("message");
        Object sevObj = body.get("severity");
        if (!(msgObj instanceof String) || sevObj == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "message and severity required"));
        }
        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("message", msgObj);
            payload.put("severity", sevObj);
            payload.put("ts", Instant.now().toString());
            String json = mapper.writeValueAsString(payload);
            redis.opsForValue().set("banner", json, Duration.ofSeconds(3600));
            return ResponseEntity.ok(payload);
        } catch (Exception e) {
            log.error("status-page: POST /incident/banner redis: {}", e.toString());
            return ResponseEntity.status(503).body(Map.of("error", "redis error"));
        }
    }

    @GetMapping("/incident/banner")
    public ResponseEntity<?> getBanner() {
        try {
            String json = redis.opsForValue().get("banner");
            if (json == null) {
                return ResponseEntity.status(404).body(Map.of("error", "no banner"));
            }
            Map<?, ?> parsed = mapper.readValue(json, Map.class);
            return ResponseEntity.ok(parsed);
        } catch (Exception e) {
            log.error("status-page: GET /incident/banner redis: {}", e.toString());
            return ResponseEntity.status(503).body(Map.of("error", "redis error"));
        }
    }
}
