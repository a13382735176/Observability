package com.vibe.promoengine;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
public class PromoController {
    private static final Logger log = LoggerFactory.getLogger(PromoController.class);
    private static final String SERVICE = "promo-engine";
    private static final String CACHE_PREFIX = "promo:";
    private static final Duration CACHE_TTL = Duration.ofSeconds(600);

    @Autowired private PromoRepository repo;
    @Autowired private PromoRedemptionRepository redemptionRepo;
    @Autowired private StringRedisTemplate redis;

    private final ObjectMapper mapper = new ObjectMapper();

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/promos")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        String code = (String) body.get("code");
        Object pctObj = body.get("discount_pct");
        String validUntilIso = (String) body.get("valid_until_iso");
        if (code == null || pctObj == null || validUntilIso == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "code, discount_pct, valid_until_iso required"));
        }
        int pct;
        OffsetDateTime validUntil;
        try {
            pct = ((Number) pctObj).intValue();
            validUntil = OffsetDateTime.parse(validUntilIso);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", "invalid discount_pct or valid_until_iso"));
        }

        Promo promo;
        try {
            Optional<Promo> existing = repo.findByCode(code);
            promo = existing.orElseGet(Promo::new);
            promo.setCode(code);
            promo.setDiscountPct(pct);
            promo.setValidUntil(validUntil);
            promo.setActive(true);
            if (promo.getCreatedAt() == null) promo.setCreatedAt(OffsetDateTime.now());
            promo = repo.save(promo);
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }

        try {
            String json = mapper.writeValueAsString(toMap(promo));
            redis.opsForValue().set(CACHE_PREFIX + code, json, CACHE_TTL);
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
        }

        return ResponseEntity.status(201).body(toMap(promo));
    }

    @PostMapping("/apply")
    public ResponseEntity<?> apply(@RequestBody Map<String, Object> body) {
        String code = (String) body.get("code");
        Object subObj = body.get("subtotal_cents");
        if (code == null || subObj == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "code, subtotal_cents required"));
        }
        long subtotal;
        try {
            subtotal = ((Number) subObj).longValue();
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", "invalid subtotal_cents"));
        }

        Map<String, Object> promoData = null;
        try {
            String cached = redis.opsForValue().get(CACHE_PREFIX + code);
            if (cached != null) {
                promoData = mapper.readValue(cached, Map.class);
            }
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
        }

        if (promoData == null) {
            try {
                Optional<Promo> existing = repo.findByCodeAndActiveTrue(code);
                if (existing.isEmpty()) {
                    return ResponseEntity.status(404).body(Map.of("error", "promo not found"));
                }
                Promo promo = existing.get();
                promoData = toMap(promo);
                try {
                    redis.opsForValue().set(CACHE_PREFIX + code, mapper.writeValueAsString(promoData), CACHE_TTL);
                } catch (Exception e) {
                    log.error("promo-engine: {}", e.getMessage(), e);
                }
            } catch (Exception e) {
                log.error("promo-engine: {}", e.getMessage(), e);
                return ResponseEntity.status(503).body(Map.of("error", "db error"));
            }
        }

        Object validUntilObj = promoData.get("valid_until");
        if (validUntilObj != null) {
            try {
                OffsetDateTime validUntil = OffsetDateTime.parse(validUntilObj.toString());
                if (!validUntil.isAfter(OffsetDateTime.now())) {
                    return ResponseEntity.status(410).body(Map.of("error", "promo expired"));
                }
            } catch (Exception e) {
                log.error("promo-engine: {}", e.getMessage(), e);
            }
        }

        int pct = ((Number) promoData.get("discount_pct")).intValue();
        long discount = subtotal * pct / 100L;
        long finalCents = subtotal - discount;

        return ResponseEntity.ok(Map.of(
                "code", code,
                "original_cents", subtotal,
                "discount_cents", discount,
                "final_cents", finalCents
        ));
    }

    @DeleteMapping("/promos/{code}")
    public ResponseEntity<?> deactivate(@PathVariable String code) {
        try {
            Optional<Promo> existing = repo.findByCode(code);
            if (existing.isEmpty()) {
                return ResponseEntity.status(404).body(Map.of("error", "promo not found"));
            }
            Promo promo = existing.get();
            promo.setActive(false);
            repo.save(promo);
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
        try {
            redis.delete(CACHE_PREFIX + code);
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
        }
        return ResponseEntity.ok(Map.of("code", code, "active", false));
    }

    @GetMapping("/promos")
    public ResponseEntity<?> list() {
        try {
            List<Map<String, Object>> rows = repo.findByActiveTrue().stream().map(this::toMap).toList();
            return ResponseEntity.ok(rows);
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @PostMapping("/promos/{code}/redeem")
    public ResponseEntity<?> redeem(@PathVariable String code, @RequestBody Map<String, Object> body) {
        String userId = (String) body.get("user_id");
        if (userId == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "user_id required"));
        }
        try {
            PromoRedemption r = new PromoRedemption();
            r.setPromoCode(code);
            r.setUserId(userId);
            r.setRedeemedAt(OffsetDateTime.now());
            r = redemptionRepo.save(r);
            return ResponseEntity.status(201).body(Map.of(
                    "id", r.getId(),
                    "promo_code", r.getPromoCode(),
                    "user_id", r.getUserId(),
                    "redeemed_at", r.getRedeemedAt().toString()
            ));
        } catch (Exception e) {
            log.error("promo-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    private Map<String, Object> toMap(Promo p) {
        return Map.of(
                "id", p.getId() == null ? -1L : p.getId(),
                "code", p.getCode(),
                "discount_pct", p.getDiscountPct(),
                "valid_until", p.getValidUntil() == null ? "" : p.getValidUntil().toString(),
                "active", p.getActive(),
                "created_at", p.getCreatedAt() == null ? "" : p.getCreatedAt().toString()
        );
    }
}
