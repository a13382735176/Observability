package com.vibe.comment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import javax.sql.DataSource;
import java.sql.Timestamp;
import java.util.*;

@RestController
public class Controller {
    private static final Logger log = LoggerFactory.getLogger("comment-service");
    private final DataSource ds;
    public Controller(DataSource ds) { this.ds = ds; }

    @GetMapping("/healthz")
    public Map<String,String> healthz() {
        return Map.of("status","ok","service","comment-service");
    }

    @GetMapping("/comments/{post_id}")
    public ResponseEntity<?> getComments(@PathVariable int post_id) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("SELECT id,post_id,user_id,text,created_at FROM comments WHERE post_id=? ORDER BY id")) {
            ps.setInt(1, post_id);
            var rs = ps.executeQuery();
            var list = new ArrayList<Map<String,Object>>();
            while (rs.next()) list.add(Map.of("id",rs.getInt(1),"post_id",rs.getInt(2),"user_id",rs.getString(3),"text",rs.getString(4),"created_at",rs.getString(5)));
            return ResponseEntity.ok(list);
        } catch (Exception e) {
            log.error("comment-service: GET /comments/{}: {}", post_id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    record CommentIn(int post_id, String user_id, String text) {}

    @PostMapping("/comments")
    public ResponseEntity<?> addComment(@RequestBody CommentIn req) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("INSERT INTO comments(post_id,user_id,text) VALUES(?,?,?) RETURNING id,post_id,user_id,text,created_at")) {
            ps.setInt(1, req.post_id()); ps.setString(2, req.user_id()); ps.setString(3, req.text());
            var rs = ps.executeQuery();
            rs.next();
            return ResponseEntity.status(201).body(Map.of("id",rs.getInt(1),"post_id",rs.getInt(2),"user_id",rs.getString(3),"text",rs.getString(4),"created_at",rs.getString(5)));
        } catch (Exception e) {
            log.error("comment-service: POST /comments: {}", e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }

    @DeleteMapping("/comments/{id}")
    public ResponseEntity<?> deleteComment(@PathVariable int id) {
        try (var conn = ds.getConnection();
             var ps = conn.prepareStatement("DELETE FROM comments WHERE id=?")) {
            ps.setInt(1, id);
            int n = ps.executeUpdate();
            if (n == 0) return ResponseEntity.notFound().build();
            return ResponseEntity.ok(Map.of("deleted", id));
        } catch (Exception e) {
            log.error("comment-service: DELETE /comments/{}: {}", id, e.getMessage(), e);
            return ResponseEntity.status(500).body(Map.of("error","internal error"));
        }
    }
}
