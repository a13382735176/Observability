package com.vibe.account;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;
import jakarta.annotation.PostConstruct;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
public class AccountController {
    private static final Logger log = LoggerFactory.getLogger(AccountController.class);

    @Autowired private AccountRepository repo;
    private JedisPool jedisPool;

    @PostConstruct
    public void init() {
        String cacheHost = System.getenv().getOrDefault("REDIS_CACHE_HOST", "redis-cache");
        try {
            JedisPoolConfig cfg = new JedisPoolConfig();
            cfg.setMaxTotal(4);
            jedisPool = new JedisPool(cfg, cacheHost, 6379, 2000);
        } catch (Exception e) {
            log.error("account-service: redis init: {}", e.getMessage(), e);
        }
    }

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", "account-service");
    }

    @PostMapping("/accounts")
    public ResponseEntity<?> createAccount(@RequestBody Map<String, String> body) {
        try {
            Account a = new Account(body.get("user_id"), body.get("account_type"), body.get("currency"));
            repo.save(a);
            return ResponseEntity.status(201).body(a);
        } catch (Exception e) {
            log.error("account-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/accounts/{userId}")
    public ResponseEntity<?> getAccounts(@PathVariable String userId) {
        try {
            return ResponseEntity.ok(repo.findByUserId(userId));
        } catch (Exception e) {
            log.error("account-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/accounts/{id}/balance")
    public ResponseEntity<?> getBalance(@PathVariable Long id) {
        String key = "bal:" + id;
        try {
            if (jedisPool != null) {
                try (var j = jedisPool.getResource()) {
                    String cached = j.get(key);
                    if (cached != null) {
                        return ResponseEntity.ok(Map.of("account_id", id, "balance_cents", Long.parseLong(cached), "source", "cache"));
                    }
                }
            }
        } catch (Exception e) {
            log.error("account-service: redis: {}", e.getMessage(), e);
        }
        try {
            Optional<Account> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            Account a = opt.get();
            if (jedisPool != null) {
                try (var j = jedisPool.getResource()) {
                    j.setex(key, 60, a.getBalanceCents().toString());
                } catch (Exception e) {
                    log.error("account-service: redis: {}", e.getMessage(), e);
                }
            }
            return ResponseEntity.ok(Map.of("account_id", id, "balance_cents", a.getBalanceCents()));
        } catch (Exception e) {
            log.error("account-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }
}
