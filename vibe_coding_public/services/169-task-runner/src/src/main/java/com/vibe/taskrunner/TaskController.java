package com.vibe.taskrunner;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
public class TaskController {
    private static final Logger log = LoggerFactory.getLogger("task-runner");
    private static final String SERVICE = "task-runner";
    private static final String STREAM_TASKS = "events:tasks";
    private static final String STREAM_STARTED = "events:task_started";
    private static final String STREAM_FINISHED = "events:task_finished";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    private TaskRepository repo;

    @Autowired
    private StringRedisTemplate redisStreamTemplate;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/tasks")
    public ResponseEntity<?> create(@RequestBody Map<String, Object> body) {
        String type = (String) body.get("type");
        if (type == null || type.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "type required"));
        }
        String parameters = "{}";
        Object paramObj = body.get("parameters");
        if (paramObj != null) {
            try {
                parameters = MAPPER.writeValueAsString(paramObj);
            } catch (Exception e) {
                return ResponseEntity.badRequest().body(Map.of("error", "parameters must be JSON object"));
            }
        }
        try {
            Task t = new Task();
            t.setType(type);
            t.setParameters(parameters);
            t.setStatus("queued");
            t.setCreatedAt(OffsetDateTime.now());
            Task saved = repo.save(t);
            try {
                Map<String, String> fields = new HashMap<>();
                fields.put("id", String.valueOf(saved.getId()));
                fields.put("type", type);
                MapRecord<String, String, String> record = StreamRecords.mapBacked(fields).withStreamKey(STREAM_TASKS);
                redisStreamTemplate.opsForStream().add(record);
            } catch (Exception e) {
                log.error("task-runner: stream publish events:tasks: {}", e.getMessage(), e);
            }
            return ResponseEntity.status(201).body(toJson(saved));
        } catch (Exception e) {
            log.error("task-runner: POST /tasks: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/tasks/{id}")
    public ResponseEntity<?> get(@PathVariable Long id) {
        try {
            Optional<Task> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            return ResponseEntity.ok(toJson(opt.get()));
        } catch (Exception e) {
            log.error("task-runner: GET /tasks/{}: {}", id, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @PostMapping("/tasks/{id}/start")
    public ResponseEntity<?> start(@PathVariable Long id) {
        try {
            Optional<Task> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            Task t = opt.get();
            t.setStatus("running");
            t.setStartedAt(OffsetDateTime.now());
            Task saved = repo.save(t);
            try {
                Map<String, String> fields = new HashMap<>();
                fields.put("id", String.valueOf(saved.getId()));
                fields.put("type", saved.getType() == null ? "" : saved.getType());
                MapRecord<String, String, String> record = StreamRecords.mapBacked(fields).withStreamKey(STREAM_STARTED);
                redisStreamTemplate.opsForStream().add(record);
            } catch (Exception e) {
                log.error("task-runner: stream publish events:task_started: {}", e.getMessage(), e);
            }
            return ResponseEntity.ok(toJson(saved));
        } catch (Exception e) {
            log.error("task-runner: POST /tasks/{}/start: {}", id, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @PostMapping("/tasks/{id}/finish")
    public ResponseEntity<?> finish(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        String output = (String) body.get("output");
        Object successObj = body.get("success");
        if (successObj == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "success required"));
        }
        boolean success = Boolean.TRUE.equals(successObj) || "true".equalsIgnoreCase(String.valueOf(successObj));
        String status = success ? "success" : "failed";
        try {
            Optional<Task> opt = repo.findById(id);
            if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("error", "not found"));
            Task t = opt.get();
            t.setStatus(status);
            t.setFinishedAt(OffsetDateTime.now());
            if (output != null) t.setOutput(output);
            Task saved = repo.save(t);
            try {
                Map<String, String> fields = new HashMap<>();
                fields.put("id", String.valueOf(saved.getId()));
                fields.put("status", status);
                MapRecord<String, String, String> record = StreamRecords.mapBacked(fields).withStreamKey(STREAM_FINISHED);
                redisStreamTemplate.opsForStream().add(record);
            } catch (Exception e) {
                log.error("task-runner: stream publish events:task_finished: {}", e.getMessage(), e);
            }
            return ResponseEntity.ok(toJson(saved));
        } catch (Exception e) {
            log.error("task-runner: POST /tasks/{}/finish: {}", id, e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/tasks")
    public ResponseEntity<?> list(@RequestParam(required = false) String status,
                                  @RequestParam(required = false) Integer limit) {
        int n = (limit == null || limit <= 0 || limit > 200) ? 50 : limit;
        try {
            List<Task> list = (status == null || status.isBlank())
                    ? repo.listRecent(n)
                    : repo.listByStatus(status, n);
            return ResponseEntity.ok(list.stream().map(this::toJson).toList());
        } catch (Exception e) {
            log.error("task-runner: GET /tasks: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    private Map<String, Object> toJson(Task t) {
        Map<String, Object> m = new HashMap<>();
        m.put("id", t.getId());
        m.put("type", t.getType());
        m.put("parameters", t.getParameters());
        m.put("status", t.getStatus());
        m.put("started_at", t.getStartedAt() == null ? null : t.getStartedAt().toString());
        m.put("finished_at", t.getFinishedAt() == null ? null : t.getFinishedAt().toString());
        m.put("output", t.getOutput());
        m.put("created_at", t.getCreatedAt() == null ? null : t.getCreatedAt().toString());
        return m;
    }
}
