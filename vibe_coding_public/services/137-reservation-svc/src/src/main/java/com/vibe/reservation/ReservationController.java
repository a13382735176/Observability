package com.vibe.reservation;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

@RestController
public class ReservationController {
    private static final Logger log = LoggerFactory.getLogger(ReservationController.class);
    private static final String SERVICE = "reservation-svc";

    @Autowired private StringRedisTemplate redis;
    @Autowired private ReservationRepository repo;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/reservations")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        try {
            String restaurantId = (String) body.get("restaurant_id");
            String userId = (String) body.get("user_id");
            Integer partySize = body.get("party_size") == null ? null : ((Number) body.get("party_size")).intValue();
            String reservationTimeStr = (String) body.get("reservation_time");
            if (restaurantId == null || userId == null || partySize == null || reservationTimeStr == null) {
                return ResponseEntity.badRequest().body(Map.of("error", "restaurant_id, user_id, party_size, reservation_time required"));
            }
            OffsetDateTime rtime = OffsetDateTime.parse(reservationTimeStr);
            Reservation r = new Reservation();
            r.setRestaurantId(restaurantId);
            r.setUserId(userId);
            r.setPartySize(partySize);
            r.setReservationTime(rtime);
            r.setStatus("confirmed");
            r.setCreatedAt(OffsetDateTime.now());
            repo.save(r);

            String dateKey = rtime.atZoneSameInstant(ZoneOffset.UTC).toLocalDate().format(DateTimeFormatter.ISO_LOCAL_DATE);
            String cacheKey = "rsv:" + restaurantId + ":" + dateKey;
            try {
                redis.opsForSet().add(cacheKey, String.valueOf(r.getId()));
            } catch (Exception e) {
                log.error("reservation-svc: redis SADD {}: {}", cacheKey, e.getMessage());
            }
            return ResponseEntity.status(201).body(toMap(r));
        } catch (Exception e) {
            log.error("reservation-svc: POST /reservations: {}", e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/reservations/{restaurantId}")
    public ResponseEntity<?> listByRestaurant(@PathVariable String restaurantId,
                                              @RequestParam(required = false) String date) {
        try {
            LocalDate day;
            try {
                day = date == null ? LocalDate.now(ZoneOffset.UTC) : LocalDate.parse(date);
            } catch (Exception e) {
                return ResponseEntity.badRequest().body(Map.of("error", "invalid date, want YYYY-MM-DD"));
            }
            String cacheKey = "rsv:" + restaurantId + ":" + day.format(DateTimeFormatter.ISO_LOCAL_DATE);
            Set<String> ids = null;
            try {
                ids = redis.opsForSet().members(cacheKey);
            } catch (Exception e) {
                log.error("reservation-svc: redis SMEMBERS {}: {}", cacheKey, e.getMessage());
            }
            if (ids != null && !ids.isEmpty()) {
                List<Long> idList = ids.stream().map(Long::parseLong).collect(Collectors.toList());
                List<Reservation> rows = repo.findAllById(idList);
                rows.sort(Comparator.comparing(Reservation::getReservationTime));
                return ResponseEntity.ok(Map.of("source", "cache", "key", cacheKey,
                        "reservations", rows.stream().map(this::toMap).collect(Collectors.toList())));
            }
            OffsetDateTime start = day.atStartOfDay().atOffset(ZoneOffset.UTC);
            OffsetDateTime end = start.plusDays(1);
            List<Reservation> rows = repo.findByRestaurantAndDay(restaurantId, start, end);
            try {
                for (Reservation r : rows) {
                    redis.opsForSet().add(cacheKey, String.valueOf(r.getId()));
                }
            } catch (Exception e) {
                log.error("reservation-svc: redis SADD warm {}: {}", cacheKey, e.getMessage());
            }
            return ResponseEntity.ok(Map.of("source", "db", "key", cacheKey,
                    "reservations", rows.stream().map(this::toMap).collect(Collectors.toList())));
        } catch (Exception e) {
            log.error("reservation-svc: GET /reservations/{}: {}", restaurantId, e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @PutMapping("/reservations/{id}/cancel")
    public ResponseEntity<?> cancel(@PathVariable Long id) {
        try {
            Optional<Reservation> opt = repo.findById(id);
            if (opt.isEmpty()) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            Reservation r = opt.get();
            r.setStatus("cancelled");
            repo.save(r);
            String dateKey = r.getReservationTime().atZoneSameInstant(ZoneOffset.UTC).toLocalDate().format(DateTimeFormatter.ISO_LOCAL_DATE);
            String cacheKey = "rsv:" + r.getRestaurantId() + ":" + dateKey;
            try {
                redis.opsForSet().remove(cacheKey, String.valueOf(r.getId()));
            } catch (Exception e) {
                log.error("reservation-svc: redis SREM {}: {}", cacheKey, e.getMessage());
            }
            return ResponseEntity.ok(toMap(r));
        } catch (Exception e) {
            log.error("reservation-svc: PUT /reservations/{}/cancel: {}", id, e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/reservations/user/{userId}")
    public ResponseEntity<?> listByUser(@PathVariable String userId) {
        try {
            List<Reservation> rows = repo.findByUserIdOrderByIdDesc(userId);
            if (rows.size() > 20) rows = rows.subList(0, 20);
            return ResponseEntity.ok(rows.stream().map(this::toMap).collect(Collectors.toList()));
        } catch (Exception e) {
            log.error("reservation-svc: GET /reservations/user/{}: {}", userId, e.getMessage());
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    private Map<String, Object> toMap(Reservation r) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", r.getId());
        m.put("restaurant_id", r.getRestaurantId());
        m.put("user_id", r.getUserId());
        m.put("party_size", r.getPartySize());
        m.put("reservation_time", r.getReservationTime() == null ? null : r.getReservationTime().toString());
        m.put("status", r.getStatus());
        m.put("created_at", r.getCreatedAt() == null ? null : r.getCreatedAt().toString());
        return m;
    }
}
