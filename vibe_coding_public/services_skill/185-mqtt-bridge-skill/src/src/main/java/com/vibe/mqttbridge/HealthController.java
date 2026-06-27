package com.vibe.mqttbridge;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
class HealthController {
    private static final Logger log = LoggerFactory.getLogger(HealthController.class);
    private final RedisStreamClient redis;

    HealthController(RedisStreamClient redis) {
        this.redis = redis;
    }

    @GetMapping(value = "/healthz", produces = MediaType.APPLICATION_JSON_VALUE)
    Map<String, Object> health(HttpServletRequest request) {
        long start = System.nanoTime();
        RedisStreamClient.RedisStatus redisStatus = redis.check();
        long latencyMs = (System.nanoTime() - start) / 1_000_000L;

        Map<String, Object> dependency = new LinkedHashMap<>();
        dependency.put("name", "redis-stream");
        dependency.put("status", redisStatus.status());
        dependency.put("stream", Env.STREAM_NAME);
        dependency.put("latency_ms", redisStatus.latencyMs());
        if (redisStatus.error() != null) {
            dependency.put("error", redisStatus.error());
        }

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("status", "ok");
        response.put("service", Env.appName());
        response.put("timestamp", Instant.now().toString());
        response.put("dependency", dependency);

        log.info("request_completed service={} operation=healthz method={} path={} status=200 latency_ms={} dependency_status={}",
                Env.appName(), request.getMethod(), request.getRequestURI(), latencyMs, redisStatus.status());
        return response;
    }
}
