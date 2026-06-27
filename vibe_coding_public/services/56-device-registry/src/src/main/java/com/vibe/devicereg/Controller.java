package com.vibe.devicereg;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import javax.sql.DataSource;
import java.util.*;

@RestController
public class Controller {
    private static final Logger log = LoggerFactory.getLogger("device-registry");
    private final DataSource ds;
    private final StringRedisTemplate redis;
    public Controller(DataSource ds, StringRedisTemplate redis) { this.ds = ds; this.redis = redis; }

    @GetMapping("/healthz")
    public Map<String,String> healthz() { return Map.of("status","ok","service","device-registry"); }

    record DeviceIn(String device_id, String type, String firmware_version) {}
    record StatusIn(String status) {}

    @PostMapping("/devices")
    public ResponseEntity<?> register(@RequestBody DeviceIn req) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("INSERT INTO devices(device_id,type,firmware_version) VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET firmware_version=EXCLUDED.firmware_version RETURNING id,device_id,type,firmware_version,status,registered_at")) {
            ps.setString(1, req.device_id()); ps.setString(2, req.type()); ps.setString(3, req.firmware_version());
            var rs = ps.executeQuery(); rs.next();
            redis.opsForValue().set("device:status:" + req.device_id(), "online");
            return ResponseEntity.status(201).body(Map.of("id",rs.getInt(1),"device_id",rs.getString(2),"type",rs.getString(3),"firmware_version",rs.getString(4),"status",rs.getString(5),"registered_at",rs.getString(6)));
        } catch (Exception e) {
            log.error("device-registry: POST /devices: {}", e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @GetMapping("/devices")
    public ResponseEntity<?> list() {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("SELECT id,device_id,type,firmware_version,status,registered_at FROM devices ORDER BY id")) {
            var rs = ps.executeQuery();
            var list = new ArrayList<Map<String,Object>>();
            while (rs.next()) list.add(Map.of("id",rs.getInt(1),"device_id",rs.getString(2),"type",rs.getString(3),"firmware_version",rs.getString(4),"status",rs.getString(5),"registered_at",rs.getString(6)));
            return ResponseEntity.ok(list);
        } catch (Exception e) {
            log.error("device-registry: GET /devices: {}", e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @GetMapping("/devices/{device_id}")
    public ResponseEntity<?> get(@PathVariable String device_id) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("SELECT id,device_id,type,firmware_version,status,registered_at FROM devices WHERE device_id=?")) {
            ps.setString(1, device_id);
            var rs = ps.executeQuery();
            if (!rs.next()) return ResponseEntity.notFound().build();
            var cached = redis.opsForValue().get("device:status:" + device_id);
            return ResponseEntity.ok(Map.of("id",rs.getInt(1),"device_id",rs.getString(2),"type",rs.getString(3),"firmware_version",rs.getString(4),"status",cached != null ? cached : rs.getString(5),"registered_at",rs.getString(6)));
        } catch (Exception e) {
            log.error("device-registry: GET /devices/{}: {}", device_id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @PutMapping("/devices/{device_id}/status")
    public ResponseEntity<?> updateStatus(@PathVariable String device_id, @RequestBody StatusIn req) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("UPDATE devices SET status=? WHERE device_id=?")) {
            ps.setString(1, req.status()); ps.setString(2, device_id);
            int n = ps.executeUpdate();
            if (n == 0) return ResponseEntity.notFound().build();
            redis.opsForValue().set("device:status:" + device_id, req.status());
            return ResponseEntity.ok(Map.of("device_id",device_id,"status",req.status()));
        } catch (Exception e) {
            log.error("device-registry: PUT /devices/{}/status: {}", device_id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }
}
