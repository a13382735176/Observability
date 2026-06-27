package com.vibe.warrantyclaims;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
public class WarrantyClaimController {
    private static final Logger log = LoggerFactory.getLogger("warranty-claims");
    private static final String SERVICE = "warranty-claims";
    private static final String STREAM_CLAIMS = "events:claims";
    private static final String STREAM_STATUS = "events:claim_status";

    @Autowired
    private WarrantyClaimRepository repo;

    @Autowired
    private StringRedisTemplate redisStreamTemplate;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/claims")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        String productId = (String) body.get("product_id");
        String userId = (String) body.get("user_id");
        String defect = (String) body.get("defect_description");
        if (productId == null || userId == null || defect == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "product_id, user_id, defect_description required"));
        }
        try {
            WarrantyClaim c = new WarrantyClaim();
            c.setProductId(productId);
            c.setUserId(userId);
            c.setDefectDescription(defect);
            c.setStatus("open");
            c.setCreatedAt(OffsetDateTime.now());
            c.setUpdatedAt(OffsetDateTime.now());
            WarrantyClaim saved = repo.save(c);
            try {
                Map<String, String> fields = new HashMap<>();
                fields.put("id", String.valueOf(saved.getId()));
                fields.put("product_id", productId);
                MapRecord<String, String, String> record = StreamRecords.mapBacked(fields).withStreamKey(STREAM_CLAIMS);
                redisStreamTemplate.opsForStream().add(record);
            } catch (Exception e) {
                log.error("warranty-claims: stream publish events:claims: {}", e.getMessage(), e);
            }
            return ResponseEntity.status(201).body(toJson(saved));
        } catch (Exception e) {
            log.error("warranty-claims: POST /claims: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/claims/{id}")
    public ResponseEntity<?> get(@PathVariable Long id) {
        try {
            Optional<WarrantyClaim> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            return ResponseEntity.ok(toJson(opt.get()));
        } catch (Exception e) {
            log.error("warranty-claims: GET /claims/{}: {}", id, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/claims/user/{userId}")
    public ResponseEntity<?> getByUser(@PathVariable String userId) {
        try {
            List<WarrantyClaim> list = repo.findTop20ByUserIdOrderByIdDesc(userId);
            return ResponseEntity.ok(list.stream().map(this::toJson).toList());
        } catch (Exception e) {
            log.error("warranty-claims: GET /claims/user/{}: {}", userId, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @PutMapping("/claims/{id}/status")
    public ResponseEntity<?> updateStatus(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        String status = (String) body.get("status");
        String resolution = (String) body.get("resolution");
        if (status == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "status required"));
        }
        try {
            Optional<WarrantyClaim> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            WarrantyClaim c = opt.get();
            c.setStatus(status);
            if (resolution != null) c.setResolution(resolution);
            c.setUpdatedAt(OffsetDateTime.now());
            WarrantyClaim saved = repo.save(c);
            try {
                Map<String, String> fields = new HashMap<>();
                fields.put("id", String.valueOf(saved.getId()));
                fields.put("status", status);
                MapRecord<String, String, String> record = StreamRecords.mapBacked(fields).withStreamKey(STREAM_STATUS);
                redisStreamTemplate.opsForStream().add(record);
            } catch (Exception e) {
                log.error("warranty-claims: stream publish events:claim_status: {}", e.getMessage(), e);
            }
            return ResponseEntity.ok(toJson(saved));
        } catch (Exception e) {
            log.error("warranty-claims: PUT /claims/{}/status: {}", id, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    private Map<String, Object> toJson(WarrantyClaim c) {
        Map<String, Object> m = new HashMap<>();
        m.put("id", c.getId());
        m.put("product_id", c.getProductId());
        m.put("user_id", c.getUserId());
        m.put("defect_description", c.getDefectDescription());
        m.put("status", c.getStatus());
        m.put("resolution", c.getResolution());
        m.put("created_at", c.getCreatedAt() == null ? null : c.getCreatedAt().toString());
        m.put("updated_at", c.getUpdatedAt() == null ? null : c.getUpdatedAt().toString());
        return m;
    }
}
