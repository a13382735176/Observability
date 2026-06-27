/*
 * 03-order-api — order creation + lookup HTTP API.
 *
 * Endpoints:
 *   GET  /healthz
 *   POST /orders   body {"user_id": "...", "items": [...]}  ->  {"id": N}
 *   GET  /orders/{id}
 *
 * Backend: Postgres (orders table) + Redis Stream (orders:queue) for fan-out.
 */
package com.vibe;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import io.javalin.Javalin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;
import redis.clients.jedis.StreamEntryID;

import java.sql.*;
import java.util.HashMap;
import java.util.Map;

public final class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final ObjectMapper M = new ObjectMapper();
    private static final String PG_URL_RAW = envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe");
    private static final String STREAM_HOST = envOr("REDIS_STREAM_HOST", "redis-stream");
    private static final int STREAM_PORT = Integer.parseInt(envOr("REDIS_STREAM_PORT", "6379"));
    private static final String STREAM_KEY = "orders:queue";

    private static JedisPool jedisPool;

    private static String envOr(String k, String d) { String v = System.getenv(k); return v == null ? d : v; }

    /** Convert "postgres://user:pass@host:port/db" -> "jdbc:postgresql://host:port/db". */
    private static String jdbcUrl() {
        int proto = PG_URL_RAW.indexOf("://");
        int at = PG_URL_RAW.indexOf('@', proto + 3);
        return "jdbc:postgresql://" + PG_URL_RAW.substring(at + 1);
    }
    private static String pgUser() {
        int proto = PG_URL_RAW.indexOf("://");
        int at = PG_URL_RAW.indexOf('@', proto + 3);
        return PG_URL_RAW.substring(proto + 3, at).split(":", 2)[0];
    }
    private static String pgPass() {
        int proto = PG_URL_RAW.indexOf("://");
        int at = PG_URL_RAW.indexOf('@', proto + 3);
        String userpass = PG_URL_RAW.substring(proto + 3, at);
        return userpass.contains(":") ? userpass.split(":", 2)[1] : "";
    }
    private static Connection pg() throws SQLException {
        java.util.Properties p = new java.util.Properties();
        p.setProperty("user", pgUser());
        p.setProperty("password", pgPass());
        p.setProperty("connectTimeout", "2");
        p.setProperty("socketTimeout", "3");
        return DriverManager.getConnection(jdbcUrl(), p);
    }

    private static void initSchema() {
        try (Connection c = pg(); Statement s = c.createStatement()) {
            s.execute("CREATE TABLE IF NOT EXISTS orders (" +
                    "  id BIGSERIAL PRIMARY KEY," +
                    "  user_id TEXT NOT NULL," +
                    "  items_json TEXT NOT NULL," +
                    "  created_at TIMESTAMPTZ DEFAULT NOW()" +
                    ")");
            log.info("orders schema ready");
        } catch (SQLException e) {
            log.error("FATAL schema init failed: {}", e.toString());
            throw new RuntimeException(e);
        }
    }

    public static void main(String[] args) {
        log.info("order-api starting");
        initSchema();
        JedisPoolConfig cfg = new JedisPoolConfig();
        cfg.setMaxTotal(8);
        jedisPool = new JedisPool(cfg, STREAM_HOST, STREAM_PORT, 2000);

        Javalin app = Javalin.create();
        app.get("/healthz", ctx -> ctx.json(Map.of("ok", true)));

        app.post("/orders", ctx -> {
            JsonNode body;
            try { body = M.readTree(ctx.body()); }
            catch (Exception e) { ctx.status(400).json(Map.of("error", "bad json: " + e.getMessage())); return; }
            String userId = body.path("user_id").asText("");
            JsonNode items = body.path("items");
            if (userId.isEmpty() || items.isMissingNode()) {
                ctx.status(400).json(Map.of("error", "user_id and items required"));
                return;
            }
            long id;
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "INSERT INTO orders(user_id, items_json) VALUES(?, ?) RETURNING id")) {
                ps.setString(1, userId);
                ps.setString(2, items.toString());
                try (ResultSet rs = ps.executeQuery()) {
                    rs.next();
                    id = rs.getLong(1);
                }
            } catch (SQLException e) {
                log.error("ERROR pg insert order failed: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
                return;
            }
            // Fan-out to redis stream — best-effort.
            try (Jedis j = jedisPool.getResource()) {
                Map<String, String> ev = new HashMap<>();
                ev.put("order_id", String.valueOf(id));
                ev.put("user_id", userId);
                ev.put("items", items.toString());
                j.xadd(STREAM_KEY, StreamEntryID.NEW_ENTRY, ev);
            } catch (Exception e) {
                log.error("ERROR redis stream xadd failed: {}", e.toString());
                // do not fail the request
            }
            ctx.status(201).json(Map.of("id", id));
        });

        app.get("/orders/{id}", ctx -> {
            long id;
            try { id = Long.parseLong(ctx.pathParam("id")); }
            catch (NumberFormatException e) { ctx.status(400).json(Map.of("error", "bad id")); return; }
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "SELECT id,user_id,items_json,created_at FROM orders WHERE id=?")) {
                ps.setLong(1, id);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) { ctx.status(404).json(Map.of("error", "not found")); return; }
                    ObjectNode out = M.createObjectNode();
                    out.put("id", rs.getLong("id"));
                    out.put("user_id", rs.getString("user_id"));
                    out.put("items_json", rs.getString("items_json"));
                    out.put("created_at", rs.getTimestamp("created_at").toInstant().toString());
                    ctx.json(out);
                }
            } catch (SQLException e) {
                log.error("ERROR pg select order failed: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
            }
        });

        app.start(8080);
        log.info("listening on :8080");
    }
}
