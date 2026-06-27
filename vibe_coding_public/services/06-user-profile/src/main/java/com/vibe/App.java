/*
 * 06-user-profile — user profile CRUD service.
 *
 * Endpoints:
 *   GET  /healthz
 *   POST /users           body {"email":"...", "name":"..."} -> {"id":N}
 *   GET  /users/{id}
 *   PUT  /users/{id}      body {"name":"..."}
 */
package com.vibe;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.javalin.Javalin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.Map;
import java.util.Properties;

public final class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final ObjectMapper M = new ObjectMapper();
    private static final String PG_URL_RAW = envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe");

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
            s.execute("CREATE TABLE IF NOT EXISTS users(" +
                    "  id BIGSERIAL PRIMARY KEY," +
                    "  email TEXT UNIQUE NOT NULL," +
                    "  name TEXT NOT NULL," +
                    "  created_at TIMESTAMPTZ DEFAULT NOW())");
            log.info("users schema ready");
        } catch (SQLException e) {
            log.error("FATAL schema init: {}", e.toString());
            throw new RuntimeException(e);
        }
    }

    public static void main(String[] args) {
        log.info("user-profile starting");
        initSchema();

        Javalin app = Javalin.create();
        app.get("/healthz", ctx -> ctx.json(Map.of("ok", true)));

        app.post("/users", ctx -> {
            JsonNode body;
            try { body = M.readTree(ctx.body()); }
            catch (Exception e) { ctx.status(400).json(Map.of("error", e.getMessage())); return; }
            String email = body.path("email").asText("");
            String name = body.path("name").asText("");
            if (email.isEmpty() || name.isEmpty()) {
                ctx.status(400).json(Map.of("error", "email and name required")); return;
            }
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "INSERT INTO users(email,name) VALUES(?,?) RETURNING id")) {
                ps.setString(1, email); ps.setString(2, name);
                try (ResultSet rs = ps.executeQuery()) {
                    rs.next();
                    ctx.status(201).json(Map.of("id", rs.getLong(1)));
                }
            } catch (SQLException e) {
                log.error("ERROR pg insert user: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
            }
        });

        app.get("/users/{id}", ctx -> {
            long id;
            try { id = Long.parseLong(ctx.pathParam("id")); }
            catch (NumberFormatException e) { ctx.status(400).json(Map.of("error", "bad id")); return; }
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "SELECT id,email,name,created_at FROM users WHERE id=?")) {
                ps.setLong(1, id);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) { ctx.status(404).json(Map.of("error", "not found")); return; }
                    ObjectNode out = M.createObjectNode();
                    out.put("id", rs.getLong("id"));
                    out.put("email", rs.getString("email"));
                    out.put("name", rs.getString("name"));
                    out.put("created_at", rs.getTimestamp("created_at").toInstant().toString());
                    ctx.json(out);
                }
            } catch (SQLException e) {
                log.error("ERROR pg select user: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
            }
        });

        app.put("/users/{id}", ctx -> {
            long id;
            try { id = Long.parseLong(ctx.pathParam("id")); }
            catch (NumberFormatException e) { ctx.status(400).json(Map.of("error", "bad id")); return; }
            JsonNode body;
            try { body = M.readTree(ctx.body()); }
            catch (Exception e) { ctx.status(400).json(Map.of("error", e.getMessage())); return; }
            String name = body.path("name").asText("");
            if (name.isEmpty()) { ctx.status(400).json(Map.of("error", "name required")); return; }
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "UPDATE users SET name=? WHERE id=?")) {
                ps.setString(1, name); ps.setLong(2, id);
                int n = ps.executeUpdate();
                if (n == 0) { ctx.status(404).json(Map.of("error", "not found")); return; }
                ctx.json(Map.of("ok", true));
            } catch (SQLException e) {
                log.error("ERROR pg update user: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
            }
        });

        app.start(8080);
        log.info("listening on :8080");
    }
}
