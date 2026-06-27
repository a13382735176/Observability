package com.vibe.thumbnailgen;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@RestController
public class ThumbnailController {
    private static final Logger log = LoggerFactory.getLogger(ThumbnailController.class);
    private static final String SERVICE = "thumbnail-generator";

    @Autowired private ThumbnailJobRepository repo;
    @Autowired private RestTemplate restTemplate;
    @Autowired private StringRedisTemplate redis;

    @Value("${upstream.url:http://mock-upstream:8080}")
    private String upstreamUrl;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/thumbnails")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        String sourceImageUrl = (String) body.get("sourceImageUrl");
        @SuppressWarnings("unchecked")
        List<Integer> sizes = (List<Integer>) body.get("sizes");
        if (sourceImageUrl == null || sizes == null || sizes.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "sourceImageUrl and sizes required"));
        }

        List<Map<String, Object>> results = new ArrayList<>();
        for (Integer size : sizes) {
            ThumbnailJob job = new ThumbnailJob();
            job.setSourceImageUrl(sourceImageUrl);
            job.setSize(size);
            job.setStatus("pending");
            job.setCreatedAt(OffsetDateTime.now());
            try {
                job = repo.save(job);
            } catch (Exception e) {
                log.error("thumbnail-generator: db save: {}", e.getMessage(), e);
                continue;
            }

            try {
                Map<String, Object> req = new HashMap<>();
                req.put("source_image_url", sourceImageUrl);
                req.put("size", size);
                @SuppressWarnings("unchecked")
                Map<String, Object> resp = restTemplate.postForObject(
                        upstreamUrl + "/thumbnail", req, Map.class);
                if (resp != null && resp.get("url") != null) {
                    String url = String.valueOf(resp.get("url"));
                    job.setStatus("complete");
                    job.setThumbnailUrl(url);
                    job.setCompletedAt(OffsetDateTime.now());
                    try {
                        repo.save(job);
                    } catch (Exception e) {
                        log.error("thumbnail-generator: db update: {}", e.getMessage(), e);
                    }
                    try {
                        String cacheKey = "thumb:" + sourceImageUrl + ":" + size;
                        redis.opsForValue().set(cacheKey, url, Duration.ofSeconds(3600));
                    } catch (Exception e) {
                        log.error("thumbnail-generator: redis set: {}", e.getMessage(), e);
                    }
                }
            } catch (Exception e) {
                log.error("thumbnail-generator: upstream call: {}", e.getMessage(), e);
            }

            Map<String, Object> entry = new HashMap<>();
            entry.put("id", job.getId());
            entry.put("size", job.getSize());
            entry.put("thumbnailUrl", job.getThumbnailUrl());
            results.add(entry);
        }
        return ResponseEntity.ok(results);
    }

    @GetMapping("/thumbnails/by-source")
    public ResponseEntity<?> bySource(@RequestParam("url") String url) {
        try {
            return ResponseEntity.ok(repo.findBySourceImageUrl(url));
        } catch (Exception e) {
            log.error("thumbnail-generator: by-source: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/thumbnails/cached/{size}")
    public ResponseEntity<?> cached(@PathVariable("size") int size,
                                    @RequestParam("url") String url) {
        try {
            String cacheKey = "thumb:" + url + ":" + size;
            String thumb = redis.opsForValue().get(cacheKey);
            if (thumb == null) {
                return ResponseEntity.status(404).body(Map.of("error", "not cached"));
            }
            return ResponseEntity.ok(Map.of("url", url, "size", size, "thumbnailUrl", thumb));
        } catch (Exception e) {
            log.error("thumbnail-generator: redis get: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "cache error"));
        }
    }

    @DeleteMapping("/thumbnails/{id}")
    public ResponseEntity<?> delete(@PathVariable("id") Long id) {
        try {
            if (!repo.existsById(id)) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            repo.deleteById(id);
            return ResponseEntity.ok(Map.of("deleted", id));
        } catch (Exception e) {
            log.error("thumbnail-generator: delete: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }
}
