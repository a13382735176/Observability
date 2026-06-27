/*
 * 09-order-processor — consume orders from a Redis Stream and persist them
 * to Postgres processed_orders table.
 *
 * Endpoints:
 *   GET /healthz
 *   GET /stats          -> {consumed, errors}
 *
 * Background thread XREADGROUP-loops on orders:queue.
 * Self-produces 1 fake order every 5s to ensure activity.
 */
package com.vibe;

import io.javalin.Javalin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;
import redis.clients.jedis.StreamEntryID;
import redis.clients.jedis.params.XReadGroupParams;
import redis.clients.jedis.resps.StreamEntry;

import java.sql.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

public final class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final String PG_URL_RAW = envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe");
    private static final String STREAM_HOST = envOr("REDIS_STREAM_HOST", "redis-stream");
    private static final int STREAM_PORT = Integer.parseInt(envOr("REDIS_STREAM_PORT", "6379"));
    private static final String STREAM_KEY = "orders:queue";
    private static final String GROUP = "processors";
    private static final String CONSUMER = "p1";

    private static final AtomicLong CONSUMED = new AtomicLong();
    private static final AtomicLong ERRORS = new AtomicLong();

    private static JedisPool jedisPool;

    private static String envOr(String k, String d) { String v = System.getenv(k); return v == null ? d : v; }

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
        String up = PG_URL_RAW.substring(proto + 3, at);
        return up.contains(":") ? up.split(":", 2)[1] : "";
    }
    private static Connection pg() throws SQLException {
        Properties p = new Properties();
        p.setProperty("user", pgUser()); p.setProperty("password", pgPass());
        p.setProperty("connectTimeout", "2"); p.setProperty("socketTimeout", "3");
        return DriverManager.getConnection(jdbcUrl(), p);
    }

    private static void initSchema() {
        try (Connection c = pg(); Statement s = c.createStatement()) {
            s.execute("CREATE TABLE IF NOT EXISTS processed_orders(" +
                    "  id BIGSERIAL PRIMARY KEY," +
                    "  source_order_id TEXT NOT NULL," +
                    "  user_id TEXT NOT NULL," +
                    "  payload TEXT NOT NULL," +
                    "  processed_at TIMESTAMPTZ DEFAULT NOW())");
            log.info("processed_orders schema ready");
        } catch (SQLException e) {
            log.error("FATAL schema init: {}", e.toString());
            throw new RuntimeException(e);
        }
    }

    static void ensureGroup() {
        try (Jedis j = jedisPool.getResource()) {
            try {
                j.xgroupCreate(STREAM_KEY, GROUP, new StreamEntryID(0, 0), true);
            } catch (Exception e) {
                if (!e.getMessage().contains("BUSYGROUP")) {
                    log.warn("xgroupCreate: {}", e.toString());
                }
            }
        }
    }

    static void producerLoop() {
        int i = 0;
        while (true) {
            try (Jedis j = jedisPool.getResource()) {
                Map<String, String> ev = new HashMap<>();
                ev.put("order_id", String.valueOf(System.currentTimeMillis()));
                ev.put("user_id", "u" + (i++ % 10));
                ev.put("items", "[\"widget\"]");
                j.xadd(STREAM_KEY, StreamEntryID.NEW_ENTRY, ev);
            } catch (Exception e) {
                log.error("ERROR producer xadd: {}", e.toString());
            }
            try { Thread.sleep(5000); } catch (InterruptedException e) { return; }
        }
    }

    static void consumerLoop() {
        while (true) {
            List<Map.Entry<String, List<StreamEntry>>> batch;
            try (Jedis j = jedisPool.getResource()) {
                Map<String, StreamEntryID> streams = new HashMap<>();
                streams.put(STREAM_KEY, StreamEntryID.XREADGROUP_UNDELIVERED_ENTRY);
                batch = j.xreadGroup(GROUP, CONSUMER,
                        XReadGroupParams.xReadGroupParams().count(10).block(2000),
                        streams);
            } catch (Exception e) {
                ERRORS.incrementAndGet();
                log.error("ERROR xreadgroup: {}", e.toString());
                try { Thread.sleep(500); } catch (InterruptedException ie) { return; }
                continue;
            }
            if (batch == null || batch.isEmpty()) continue;
            for (Map.Entry<String, List<StreamEntry>> s : batch) {
                for (StreamEntry msg : s.getValue()) {
                    try (Connection c = pg();
                         PreparedStatement ps = c.prepareStatement(
                                 "INSERT INTO processed_orders(source_order_id,user_id,payload) VALUES(?,?,?)")) {
                        ps.setString(1, msg.getFields().getOrDefault("order_id", "?"));
                        ps.setString(2, msg.getFields().getOrDefault("user_id", "?"));
                        ps.setString(3, msg.getFields().toString());
                        ps.executeUpdate();
                        try (Jedis j = jedisPool.getResource()) {
                            j.xack(STREAM_KEY, GROUP, msg.getID());
                        }
                        CONSUMED.incrementAndGet();
                    } catch (Exception e) {
                        ERRORS.incrementAndGet();
                        log.error("ERROR processing message {}: {}", msg.getID(), e.toString());
                    }
                }
            }
        }
    }

    public static void main(String[] args) {
        log.info("order-processor starting");
        JedisPoolConfig cfg = new JedisPoolConfig();
        cfg.setMaxTotal(8);
        jedisPool = new JedisPool(cfg, STREAM_HOST, STREAM_PORT, 2000);
        initSchema();
        ensureGroup();

        Thread tProd = new Thread(App::producerLoop, "producer");
        Thread tCons = new Thread(App::consumerLoop, "consumer");
        tProd.setDaemon(true); tCons.setDaemon(true);
        tProd.start(); tCons.start();

        Javalin app = Javalin.create();
        app.get("/healthz", ctx -> ctx.json(Map.of("ok", true)));
        app.get("/stats", ctx -> ctx.json(Map.of(
                "consumed", CONSUMED.get(), "errors", ERRORS.get())));
        app.start(8080);
        log.info("listening on :8080");
    }
}
