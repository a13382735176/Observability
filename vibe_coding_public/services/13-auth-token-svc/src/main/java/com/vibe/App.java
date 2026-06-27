/*
 * 13-auth-token-svc — issue + verify JWT-like tokens backed by a Postgres
 * users table. Tokens are HS256 with header "{\"alg\":\"HS256\"}".
 *
 * Endpoints:
 *   GET  /healthz
 *   POST /signup   {"email":"...","password":"..."}        -> {"id":N}
 *   POST /token    {"email":"...","password":"..."}        -> {"token":"..."}
 *   GET  /verify   header Authorization: Bearer <token>    -> {"sub":N,"email":"..."}
 */
package com.vibe;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.javalin.Javalin;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.util.Base64;
import java.util.Map;
import java.util.Properties;

public final class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final ObjectMapper M = new ObjectMapper();
    private static final String PG_URL_RAW = envOr("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe");
    private static final String SECRET = envOr("JWT_SECRET", "vibe-coding-not-secure");
    private static final long TTL_S = 3600;

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
            s.execute("CREATE TABLE IF NOT EXISTS auth_users(" +
                    "  id BIGSERIAL PRIMARY KEY," +
                    "  email TEXT UNIQUE NOT NULL," +
                    "  pass_sha256 TEXT NOT NULL)");
            log.info("auth_users schema ready");
        } catch (SQLException e) {
            log.error("FATAL schema init: {}", e.toString());
            throw new RuntimeException(e);
        }
    }

    private static String sha256(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) { throw new RuntimeException(e); }
    }

    private static String b64url(byte[] b) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }
    private static byte[] hmacSHA256(String data) {
        try {
            Mac m = Mac.getInstance("HmacSHA256");
            m.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return m.doFinal(data.getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) { throw new RuntimeException(e); }
    }
    private static String issueToken(long uid, String email) {
        String header = b64url("{\"alg\":\"HS256\",\"typ\":\"JWT\"}".getBytes());
        long exp = System.currentTimeMillis() / 1000 + TTL_S;
        String payload = b64url(("{\"sub\":" + uid + ",\"email\":\"" + email + "\",\"exp\":" + exp + "}")
                .getBytes(StandardCharsets.UTF_8));
        String unsigned = header + "." + payload;
        String sig = b64url(hmacSHA256(unsigned));
        return unsigned + "." + sig;
    }
    private static JsonNode verifyToken(String token) throws Exception {
        String[] parts = token.split("\\.");
        if (parts.length != 3) throw new IllegalArgumentException("malformed token");
        String unsigned = parts[0] + "." + parts[1];
        byte[] expected = hmacSHA256(unsigned);
        byte[] got = Base64.getUrlDecoder().decode(parts[2]);
        if (!MessageDigest.isEqual(expected, got)) throw new SecurityException("bad signature");
        JsonNode claims = M.readTree(Base64.getUrlDecoder().decode(parts[1]));
        long exp = claims.path("exp").asLong();
        if (exp < System.currentTimeMillis() / 1000) throw new SecurityException("expired");
        return claims;
    }

    public static void main(String[] args) {
        log.info("auth-token-svc starting");
        initSchema();
        Javalin app = Javalin.create();
        app.get("/healthz", ctx -> ctx.json(Map.of("ok", true)));

        app.post("/signup", ctx -> {
            JsonNode b = M.readTree(ctx.body());
            String email = b.path("email").asText("");
            String pass = b.path("password").asText("");
            if (email.isEmpty() || pass.length() < 4) {
                ctx.status(400).json(Map.of("error", "email and pass(>=4) required")); return;
            }
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "INSERT INTO auth_users(email,pass_sha256) VALUES(?,?) RETURNING id")) {
                ps.setString(1, email); ps.setString(2, sha256(pass));
                try (ResultSet rs = ps.executeQuery()) {
                    rs.next();
                    ctx.status(201).json(Map.of("id", rs.getLong(1)));
                }
            } catch (SQLException e) {
                log.error("ERROR pg signup: {}", e.toString());
                if (e.getMessage() != null && e.getMessage().contains("duplicate")) {
                    ctx.status(409).json(Map.of("error", "email exists"));
                } else {
                    ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
                }
            }
        });

        app.post("/token", ctx -> {
            JsonNode b = M.readTree(ctx.body());
            String email = b.path("email").asText("");
            String pass = b.path("password").asText("");
            try (Connection c = pg();
                 PreparedStatement ps = c.prepareStatement(
                         "SELECT id,email,pass_sha256 FROM auth_users WHERE email=?")) {
                ps.setString(1, email);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) { ctx.status(401).json(Map.of("error", "invalid")); return; }
                    if (!rs.getString("pass_sha256").equals(sha256(pass))) {
                        ctx.status(401).json(Map.of("error", "invalid")); return;
                    }
                    ctx.json(Map.of("token", issueToken(rs.getLong("id"), rs.getString("email"))));
                }
            } catch (SQLException e) {
                log.error("ERROR pg token select: {}", e.toString());
                ctx.status(502).json(Map.of("error", "postgres error: " + e.getMessage()));
            }
        });

        app.get("/verify", ctx -> {
            String auth = ctx.header("Authorization");
            if (auth == null || !auth.startsWith("Bearer ")) {
                ctx.status(401).json(Map.of("error", "no bearer token")); return;
            }
            try {
                JsonNode claims = verifyToken(auth.substring(7));
                ctx.json(claims);
            } catch (Exception e) {
                ctx.status(401).json(Map.of("error", "invalid token: " + e.getMessage()));
            }
        });

        app.start(8080);
        log.info("listening on :8080");
    }
}
