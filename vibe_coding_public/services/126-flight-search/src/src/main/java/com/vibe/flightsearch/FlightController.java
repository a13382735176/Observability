package com.vibe.flightsearch;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

@RestController
public class FlightController {
    private static final Logger log = LoggerFactory.getLogger(FlightController.class);
    private static final String SERVICE = "flight-search";

    @Autowired private StringRedisTemplate redis;
    @Autowired private RestTemplate restTemplate;
    @Autowired private FlightCacheRepository repo;

    @Value("${upstream.url:http://mock-upstream:8080}")
    private String upstreamUrl;

    private final ObjectMapper mapper = new ObjectMapper();

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/flights/search")
    public ResponseEntity<?> searchPost(@RequestBody Map<String, Object> body) {
        String origin = (String) body.get("origin");
        String dest = (String) body.get("dest");
        String date = (String) body.get("date");
        return doSearch(origin, dest, date);
    }

    @GetMapping("/flights/search")
    public ResponseEntity<?> searchGet(@RequestParam String origin,
                                       @RequestParam String dest,
                                       @RequestParam String date) {
        return doSearch(origin, dest, date);
    }

    private ResponseEntity<?> doSearch(String origin, String dest, String date) {
        if (origin == null || dest == null || date == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "origin, dest, date required"));
        }
        String cacheKey = "flight:" + origin + ":" + dest + ":" + date;
        try {
            String cached = (String) redis.opsForHash().get(cacheKey, "data");
            if (cached != null) {
                return ResponseEntity.ok(Map.of("source", "cache", "key", cacheKey, "data", mapper.readTree(cached)));
            }
        } catch (Exception e) {
            log.error("flight-search: redis read failed: {}", e.getMessage());
        }

        Object upstreamBody;
        String upstreamRaw;
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            Map<String, Object> req = new HashMap<>();
            req.put("origin", origin);
            req.put("dest", dest);
            req.put("date", date);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(req, headers);
            ResponseEntity<String> resp = restTemplate.exchange(
                    upstreamUrl + "/flights", HttpMethod.POST, entity, String.class);
            upstreamRaw = resp.getBody() == null ? "{}" : resp.getBody();
            upstreamBody = mapper.readTree(upstreamRaw);
        } catch (Exception e) {
            log.error("flight-search: upstream call failed: {}", e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "upstream error"));
        }

        try {
            redis.opsForHash().put(cacheKey, "data", upstreamRaw);
            redis.expire(cacheKey, Duration.ofSeconds(300));
        } catch (Exception e) {
            log.error("flight-search: redis write failed: {}", e.getMessage());
        }

        try {
            LocalDate flyDate = LocalDate.parse(date);
            Optional<FlightCache> existing = repo.findByOriginAndDestAndFlyDate(origin, dest, flyDate);
            FlightCache row = existing.orElseGet(FlightCache::new);
            row.setOrigin(origin);
            row.setDest(dest);
            row.setFlyDate(flyDate);
            row.setData(upstreamRaw);
            row.setCachedAt(OffsetDateTime.now());
            repo.save(row);
        } catch (Exception e) {
            log.error("flight-search: db persist failed: {}", e.getMessage());
        }

        return ResponseEntity.ok(Map.of("source", "upstream", "key", cacheKey, "data", upstreamBody));
    }

    @PostMapping("/flights/cache-populate")
    public ResponseEntity<?> cachePopulate(@RequestBody Map<String, Object> body) {
        String origin = (String) body.get("origin");
        String dest = (String) body.get("dest");
        String date = (String) body.get("date");
        Object data = body.get("data");
        if (origin == null || dest == null || date == null || data == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "origin, dest, date, data required"));
        }
        String cacheKey = "flight:" + origin + ":" + dest + ":" + date;
        try {
            String raw = mapper.writeValueAsString(data);
            try {
                redis.opsForHash().put(cacheKey, "data", raw);
                redis.expire(cacheKey, Duration.ofSeconds(300));
            } catch (Exception e) {
                log.error("flight-search: redis write failed: {}", e.getMessage());
            }
            try {
                LocalDate flyDate = LocalDate.parse(date);
                Optional<FlightCache> existing = repo.findByOriginAndDestAndFlyDate(origin, dest, flyDate);
                FlightCache row = existing.orElseGet(FlightCache::new);
                row.setOrigin(origin);
                row.setDest(dest);
                row.setFlyDate(flyDate);
                row.setData(raw);
                row.setCachedAt(OffsetDateTime.now());
                repo.save(row);
            } catch (Exception e) {
                log.error("flight-search: db persist failed: {}", e.getMessage());
            }
            return ResponseEntity.status(201).body(Map.of("key", cacheKey, "ok", true));
        } catch (Exception e) {
            log.error("flight-search: POST /flights/cache-populate: {}", e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }
}
