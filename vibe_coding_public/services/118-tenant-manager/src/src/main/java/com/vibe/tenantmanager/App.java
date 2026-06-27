package com.vibe.tenantmanager;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;

import javax.sql.DataSource;
import java.util.*;

@SpringBootApplication
@RestController
public class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);

    @Value("${REDIS_CACHE_HOST:redis-cache}") String redisHost;
    @Value("${REDIS_CACHE_PORT:6379}") int redisPort;

    private final JdbcTemplate jdbc;
    private final JedisPool pool;

    public App(DataSource ds, @Value("${REDIS_CACHE_HOST:redis-cache}") String h,
               @Value("${REDIS_CACHE_PORT:6379}") int p) {
        this.jdbc = new JdbcTemplate(ds);
        JedisPoolConfig cfg = new JedisPoolConfig();
        cfg.setMaxTotal(8);
        this.pool = new JedisPool(cfg, h, p, 2000);
    }

    public static void main(String[] args) { SpringApplication.run(App.class, args); }

    @Bean
    CommandLineRunner init() {
        return args -> {
            try {
                jdbc.execute("CREATE TABLE IF NOT EXISTS tenants (id SERIAL PRIMARY KEY, name TEXT NOT NULL, plan TEXT NOT NULL, domain TEXT UNIQUE NOT NULL, active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW())");
                log.info("tenant-manager: postgres ready");
            } catch (Exception e) {
                log.error("tenant-manager: db init: {}", e.getMessage(), e);
            }
        };
    }

    @GetMapping("/healthz")
    public Map<String, String> healthz() { return Map.of("status", "ok", "service", "tenant-manager"); }

    @PostMapping("/tenants")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        Object name = body.get("name"), plan = body.get("plan"), domain = body.get("domain");
        if (name == null || plan == null || domain == null)
            return ResponseEntity.badRequest().body(Map.of("error", "name, plan, domain required"));
        try {
            Long id = jdbc.queryForObject(
                "INSERT INTO tenants(name, plan, domain) VALUES(?,?,?) RETURNING id",
                Long.class, name.toString(), plan.toString(), domain.toString());
            Map<String, Object> tenant = Map.of("id", id, "name", name, "plan", plan, "domain", domain, "active", true);
            cacheTenant(id, tenant);
            return ResponseEntity.status(201).body(tenant);
        } catch (Exception e) {
            log.error("tenant-manager: create: {}", e.getMessage(), e);
            return ResponseEntity.status(502).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/tenants/{id}")
    public ResponseEntity<?> get(@PathVariable long id) {
        try (Jedis j = pool.getResource()) {
            Map<String, String> cached = j.hgetAll("tenant:" + id);
            if (!cached.isEmpty()) return ResponseEntity.ok(cached);
        } catch (Exception e) {
            log.error("tenant-manager: cache get: {}", e.getMessage(), e);
        }
        try {
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, name, plan, domain, active FROM tenants WHERE id=?", id);
            if (rows.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            Map<String, Object> t = rows.get(0);
            cacheTenant(id, t);
            return ResponseEntity.ok(t);
        } catch (Exception e) {
            log.error("tenant-manager: db get: {}", e.getMessage(), e);
            return ResponseEntity.status(502).body(Map.of("error", "db error"));
        }
    }

    @PutMapping("/tenants/{id}/plan")
    public ResponseEntity<?> updatePlan(@PathVariable long id, @RequestBody Map<String, Object> body) {
        Object plan = body.get("plan");
        if (plan == null) return ResponseEntity.badRequest().body(Map.of("error", "plan required"));
        try {
            int n = jdbc.update("UPDATE tenants SET plan=? WHERE id=?", plan.toString(), id);
            if (n == 0) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            try (Jedis j = pool.getResource()) { j.hset("tenant:" + id, "plan", plan.toString()); }
            catch (Exception e) { log.error("tenant-manager: cache update: {}", e.getMessage(), e); }
            return ResponseEntity.ok(Map.of("id", id, "plan", plan));
        } catch (Exception e) {
            log.error("tenant-manager: update plan: {}", e.getMessage(), e);
            return ResponseEntity.status(502).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/tenants")
    public ResponseEntity<?> list() {
        try {
            return ResponseEntity.ok(jdbc.queryForList(
                "SELECT id, name, plan, domain, active FROM tenants ORDER BY id"));
        } catch (Exception e) {
            log.error("tenant-manager: list: {}", e.getMessage(), e);
            return ResponseEntity.status(502).body(Map.of("error", "db error"));
        }
    }

    private void cacheTenant(long id, Map<String, Object> t) {
        try (Jedis j = pool.getResource()) {
            Map<String, String> m = new HashMap<>();
            t.forEach((k, v) -> m.put(k, String.valueOf(v)));
            j.hset("tenant:" + id, m);
        } catch (Exception e) {
            log.error("tenant-manager: cache set: {}", e.getMessage(), e);
        }
    }
}
