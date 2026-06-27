package com.vibe.dm;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;
import javax.sql.DataSource;
import java.util.*;

@RestController
public class Controller {
    private static final Logger log = LoggerFactory.getLogger("dm-service");
    private final DataSource ds;
    private final JedisPool jedisPool;

    public Controller(DataSource ds) {
        this.ds = ds;
        String host = System.getenv().getOrDefault("REDIS_STREAM_HOST", "redis-stream");
        int port = Integer.parseInt(System.getenv().getOrDefault("REDIS_STREAM_PORT", "6379"));
        var cfg = new JedisPoolConfig();
        cfg.setMaxTotal(5);
        this.jedisPool = new JedisPool(cfg, host, port, 2000);
    }

    @GetMapping("/healthz")
    public Map<String,String> healthz() { return Map.of("status","ok","service","dm-service"); }

    record MsgIn(String sender_id, String recipient_id, String text) {}

    @PostMapping("/messages")
    public ResponseEntity<?> sendMessage(@RequestBody MsgIn req) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("INSERT INTO messages(sender_id,recipient_id,text) VALUES(?,?,?) RETURNING id,sender_id,recipient_id,text,read,created_at")) {
            ps.setString(1, req.sender_id()); ps.setString(2, req.recipient_id()); ps.setString(3, req.text());
            var rs = ps.executeQuery(); rs.next();
            var result = Map.of("id",rs.getInt(1),"sender_id",rs.getString(2),"recipient_id",rs.getString(3),"text",rs.getString(4),"read",rs.getBoolean(5),"created_at",rs.getString(6));
            try (var jedis = jedisPool.getResource()) {
                jedis.xadd("events:messages", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                    Map.of("event","message.sent","sender_id",req.sender_id(),"recipient_id",req.recipient_id()));
            } catch (Exception e) {
                log.error("dm-service: stream publish: {}", e.getMessage(), e);
            }
            return ResponseEntity.status(201).body(result);
        } catch (Exception e) {
            log.error("dm-service: POST /messages: {}", e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @GetMapping("/messages/{conv_id}")
    public ResponseEntity<?> getMessages(@PathVariable String conv_id) {
        // conv_id = "sender_id:recipient_id"
        try {
            String[] parts = conv_id.split(":");
            if (parts.length != 2) return ResponseEntity.badRequest().body(Map.of("error","conv_id must be sender_id:recipient_id"));
            try (var conn = ds.getConnection();
                 var ps = conn.prepareStatement("SELECT id,sender_id,recipient_id,text,read,created_at FROM messages WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?) ORDER BY id")) {
                ps.setString(1, parts[0]); ps.setString(2, parts[1]); ps.setString(3, parts[1]); ps.setString(4, parts[0]);
                var rs = ps.executeQuery();
                var list = new ArrayList<Map<String,Object>>();
                while (rs.next()) list.add(Map.of("id",rs.getInt(1),"sender_id",rs.getString(2),"recipient_id",rs.getString(3),"text",rs.getString(4),"read",rs.getBoolean(5),"created_at",rs.getString(6)));
                return ResponseEntity.ok(list);
            }
        } catch (Exception e) {
            log.error("dm-service: GET /messages/{}: {}", conv_id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }
}
