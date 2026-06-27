package com.vibe.policyengine;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@RestController
public class PolicyController {
    private static final Logger log = LoggerFactory.getLogger(PolicyController.class);
    private static final String SERVICE = "policy-engine";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired private StringRedisTemplate redis;
    @Autowired private PolicyRepository repo;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/policies")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        try {
            String name = (String) body.get("name");
            String effect = (String) body.get("effect");
            String resourcePattern = (String) body.get("resource_pattern");
            String actionPattern = (String) body.get("action_pattern");
            String principalPattern = (String) body.get("principal_pattern");
            if (name == null || effect == null || resourcePattern == null
                    || actionPattern == null || principalPattern == null) {
                return ResponseEntity.badRequest().body(Map.of(
                        "error", "name, effect, resource_pattern, action_pattern, principal_pattern required"));
            }
            if (!"allow".equals(effect) && !"deny".equals(effect)) {
                return ResponseEntity.badRequest().body(Map.of("error", "effect must be 'allow' or 'deny'"));
            }
            Policy p = new Policy();
            p.setName(name);
            p.setEffect(effect);
            p.setResourcePattern(resourcePattern);
            p.setActionPattern(actionPattern);
            p.setPrincipalPattern(principalPattern);
            p.setCreatedAt(OffsetDateTime.now());
            repo.save(p);
            return ResponseEntity.status(201).body(toMap(p));
        } catch (Exception e) {
            log.error("policy-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @PostMapping("/evaluate")
    public ResponseEntity<?> evaluate(@RequestBody Map<String, Object> body) {
        try {
            String principal = (String) body.get("principal");
            String resource = (String) body.get("resource");
            String action = (String) body.get("action");
            if (principal == null || resource == null || action == null) {
                return ResponseEntity.badRequest().body(Map.of(
                        "error", "principal, resource, action required"));
            }
            String cacheKey = "policy_decision:" + principal + ":" + resource + ":" + action;

            // Try cache.
            try {
                String cached = redis.opsForValue().get(cacheKey);
                if (cached != null) {
                    Map<String, Object> m = MAPPER.readValue(cached, Map.class);
                    return ResponseEntity.ok(m);
                }
            } catch (Exception e) {
                log.error("policy-engine: {}", e.getMessage(), e);
            }

            // Miss → consult DB.
            List<Policy> all = repo.findAll();
            Long matchedAllow = null;
            Long matchedDeny = null;
            for (Policy p : all) {
                if (!matches(p.getPrincipalPattern(), principal)) continue;
                if (!matches(p.getResourcePattern(), resource)) continue;
                if (!matches(p.getActionPattern(), action)) continue;
                if ("deny".equals(p.getEffect())) {
                    matchedDeny = p.getId();
                    break; // deny wins
                } else if ("allow".equals(p.getEffect()) && matchedAllow == null) {
                    matchedAllow = p.getId();
                }
            }

            String decision;
            Long matchedId;
            if (matchedDeny != null) {
                decision = "deny";
                matchedId = matchedDeny;
            } else if (matchedAllow != null) {
                decision = "allow";
                matchedId = matchedAllow;
            } else {
                decision = "deny";
                matchedId = null;
            }

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("decision", decision);
            result.put("matched_policy_id", matchedId);

            try {
                redis.opsForValue().set(cacheKey, MAPPER.writeValueAsString(result), 60, TimeUnit.SECONDS);
            } catch (Exception e) {
                log.error("policy-engine: {}", e.getMessage(), e);
            }
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            log.error("policy-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    private boolean matches(String pattern, String value) {
        return "*".equals(pattern) || pattern.equals(value);
    }

    @GetMapping("/policies")
    public ResponseEntity<?> list() {
        try {
            return ResponseEntity.ok(repo.findAll().stream().map(this::toMap).collect(Collectors.toList()));
        } catch (Exception e) {
            log.error("policy-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @DeleteMapping("/policies/{id}")
    public ResponseEntity<?> delete(@PathVariable Long id) {
        try {
            if (!repo.existsById(id)) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            repo.deleteById(id);
            return ResponseEntity.ok(Map.of("id", id, "deleted", true));
        } catch (Exception e) {
            log.error("policy-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @PostMapping("/policies/refresh")
    public ResponseEntity<?> refresh() {
        try {
            Set<String> keys = redis.keys("policy_decision:*");
            int n = 0;
            if (keys != null && !keys.isEmpty()) {
                Long deleted = redis.delete(keys);
                n = deleted == null ? 0 : deleted.intValue();
            }
            return ResponseEntity.ok(Map.of("cleared", n));
        } catch (Exception e) {
            log.error("policy-engine: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    private Map<String, Object> toMap(Policy p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("name", p.getName());
        m.put("effect", p.getEffect());
        m.put("resource_pattern", p.getResourcePattern());
        m.put("action_pattern", p.getActionPattern());
        m.put("principal_pattern", p.getPrincipalPattern());
        m.put("created_at", p.getCreatedAt() == null ? null : p.getCreatedAt().toString());
        return m;
    }
}
