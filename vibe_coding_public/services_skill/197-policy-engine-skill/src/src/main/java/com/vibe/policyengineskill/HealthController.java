package com.vibe.policyengineskill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {
    private static final Logger log = LoggerFactory.getLogger(HealthController.class);

    private final PolicyDecisionCache cache;
    private final RedisSettings redisSettings;
    private final Instant startedAt = Instant.now();

    public HealthController(PolicyDecisionCache cache, RedisSettings redisSettings) {
        this.cache = cache;
        this.redisSettings = redisSettings;
    }

    @GetMapping("/healthz")
    public ResponseEntity<Map<String, Object>> healthz() {
        long start = System.nanoTime();
        boolean redisAvailable = cache.ping();

        Map<String, Object> redis = new LinkedHashMap<>();
        redis.put("name", "redis-cache");
        redis.put("host", redisSettings.host());
        redis.put("port", redisSettings.port());
        redis.put("status", redisAvailable ? "ok" : "unavailable");

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "ok");
        body.put("service", serviceName());
        body.put("uptime_seconds", Duration.between(startedAt, Instant.now()).toSeconds());
        body.put("dependencies", Map.of("redis_cache", redis));

        log.info("request_complete service={} operation={} outcome={} latency_ms={}",
                serviceName(), "healthz", "success", elapsedMillis(start));
        return ResponseEntity.ok(body);
    }

    private static long elapsedMillis(long startNanos) {
        return Duration.ofNanos(System.nanoTime() - startNanos).toMillis();
    }

    private static String serviceName() {
        return System.getenv().getOrDefault("APP_NAME", "policy-engine-skill");
    }
}
