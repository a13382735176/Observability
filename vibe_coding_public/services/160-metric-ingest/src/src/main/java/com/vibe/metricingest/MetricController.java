package com.vibe.metricingest;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;

@RestController
public class MetricController {
    private static final Logger log = LoggerFactory.getLogger(MetricController.class);
    private static final String SERVICE = "metric-ingest";
    private static final int SERIES_LIMIT = 500;

    @Autowired private StringRedisTemplate redis;
    @Autowired private MetricSampleRepository repo;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/metrics")
    public ResponseEntity<?> ingest(@RequestBody Map<String, Object> body) {
        try {
            MetricSample s = toSample(body);
            repo.save(s);
            cacheLatest(s);
            return ResponseEntity.status(201).body(toMap(s));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (Exception e) {
            log.error("metric-ingest: POST /metrics: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @PostMapping("/metrics/batch")
    public ResponseEntity<?> ingestBatch(@RequestBody List<Map<String, Object>> body) {
        if (body == null || body.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("error", "empty batch"));
        }
        try {
            List<MetricSample> samples = new ArrayList<>(body.size());
            for (Map<String, Object> entry : body) {
                samples.add(toSample(entry));
            }
            List<MetricSample> saved = repo.saveAll(samples);
            for (MetricSample s : saved) {
                try { cacheLatest(s); } catch (Exception e) {
                    log.error("metric-ingest: redis cache write {}: {}", s.getName(), e.getMessage());
                }
            }
            return ResponseEntity.status(201).body(Map.of("ingested", saved.size()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (Exception e) {
            log.error("metric-ingest: POST /metrics/batch: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/metrics/{name}")
    public ResponseEntity<?> getLatest(@PathVariable String name) {
        try {
            String cached = redis.opsForValue().get(latestKey(name));
            if (cached != null) {
                return ResponseEntity.ok(Map.of("source", "cache", "name", name, "value", Double.parseDouble(cached)));
            }
        } catch (Exception e) {
            log.error("metric-ingest: redis read {}: {}", name, e.getMessage());
        }
        try {
            Optional<MetricSample> latest = repo.findFirstByNameOrderByTsDesc(name);
            if (latest.isEmpty()) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            MetricSample s = latest.get();
            try {
                redis.opsForValue().set(latestKey(name), String.valueOf(s.getValue()), Duration.ofSeconds(300));
            } catch (Exception e) {
                log.error("metric-ingest: redis cache write {}: {}", name, e.getMessage());
            }
            return ResponseEntity.ok(Map.of("source", "db", "sample", toMap(s)));
        } catch (Exception e) {
            log.error("metric-ingest: GET /metrics/{} db: {}", name, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/metrics/{name}/series")
    public ResponseEntity<?> series(@PathVariable String name,
                                    @RequestParam(name = "from") long from,
                                    @RequestParam(name = "to") long to) {
        if (to < from) {
            return ResponseEntity.badRequest().body(Map.of("error", "to < from"));
        }
        try {
            OffsetDateTime f = OffsetDateTime.ofInstant(Instant.ofEpochMilli(from), ZoneOffset.UTC);
            OffsetDateTime t = OffsetDateTime.ofInstant(Instant.ofEpochMilli(to), ZoneOffset.UTC);
            List<MetricSample> rows = repo.findSeries(name, f, t);
            if (rows.size() > SERIES_LIMIT) rows = rows.subList(0, SERIES_LIMIT);
            List<Map<String, Object>> out = new ArrayList<>(rows.size());
            for (MetricSample s : rows) out.add(toMap(s));
            return ResponseEntity.ok(out);
        } catch (Exception e) {
            log.error("metric-ingest: GET /metrics/{}/series: {}", name, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    private MetricSample toSample(Map<String, Object> body) {
        Object name = body.get("name");
        Object value = body.get("value");
        if (!(name instanceof String) || ((String) name).isEmpty()) {
            throw new IllegalArgumentException("name required");
        }
        if (!(value instanceof Number)) {
            throw new IllegalArgumentException("value required (number)");
        }
        MetricSample s = new MetricSample();
        s.setName((String) name);
        s.setValue(((Number) value).doubleValue());
        Object tagsObj = body.get("tags");
        if (tagsObj instanceof Map<?, ?> raw) {
            Map<String, String> tags = new HashMap<>();
            for (Map.Entry<?, ?> e : raw.entrySet()) {
                if (e.getKey() != null && e.getValue() != null) {
                    tags.put(e.getKey().toString(), e.getValue().toString());
                }
            }
            s.setTags(tags);
        }
        Object tsObj = body.get("ts_epoch_ms");
        if (tsObj instanceof Number n) {
            s.setTs(OffsetDateTime.ofInstant(Instant.ofEpochMilli(n.longValue()), ZoneOffset.UTC));
        } else {
            s.setTs(OffsetDateTime.now(ZoneOffset.UTC));
        }
        return s;
    }

    private void cacheLatest(MetricSample s) {
        try {
            redis.opsForValue().set(latestKey(s.getName()), String.valueOf(s.getValue()), Duration.ofSeconds(300));
        } catch (Exception e) {
            log.error("metric-ingest: redis cache write {}: {}", s.getName(), e.getMessage());
        }
    }

    private static String latestKey(String name) {
        return "metric:latest:" + name;
    }

    private static Map<String, Object> toMap(MetricSample s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", s.getId());
        m.put("name", s.getName());
        m.put("value", s.getValue());
        m.put("tags", s.getTags());
        m.put("ts_epoch_ms", s.getTs() == null ? null : s.getTs().toInstant().toEpochMilli());
        return m;
    }
}
