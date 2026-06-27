package com.vibe.mqttbridge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.*;
import java.util.stream.Collectors;

@RestController
public class MqttController {
    private static final Logger log = LoggerFactory.getLogger(MqttController.class);
    private static final String SERVICE = "mqtt-bridge";
    private static final String STREAM_KEY = "events:mqtt";

    @Autowired private StringRedisTemplate redis;
    @Autowired private MqttMessageRepository messages;
    @Autowired private SubscriptionRepository subscriptions;

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok", "service", SERVICE);
    }

    @PostMapping("/messages")
    public ResponseEntity<?> publish(@RequestBody Map<String, Object> body) {
        try {
            String topic = (String) body.get("topic");
            String payload = (String) body.get("payload");
            Integer qos = body.get("qos") == null ? null : ((Number) body.get("qos")).intValue();
            if (topic == null || payload == null || qos == null) {
                return ResponseEntity.badRequest().body(Map.of("error", "topic, payload, qos required"));
            }
            if (qos < 0 || qos > 2) {
                return ResponseEntity.badRequest().body(Map.of("error", "qos must be 0, 1, or 2"));
            }
            MqttMessage m = new MqttMessage();
            m.setTopic(topic);
            m.setPayload(payload);
            m.setQos(qos);
            m.setReceivedAt(OffsetDateTime.now());
            messages.save(m);

            try {
                Map<String, String> entry = new LinkedHashMap<>();
                entry.put("topic", topic);
                entry.put("payload", payload);
                MapRecord<String, String, String> record = StreamRecords.mapBacked(entry).withStreamKey(STREAM_KEY);
                RecordId rid = redis.opsForStream().add(record);
                return ResponseEntity.status(201).body(Map.of(
                        "id", m.getId(),
                        "topic", topic,
                        "qos", qos,
                        "stream_id", rid == null ? null : rid.getValue()
                ));
            } catch (Exception e) {
                log.error("mqtt-bridge: {}", e.getMessage(), e);
                return ResponseEntity.status(201).body(Map.of(
                        "id", m.getId(),
                        "topic", topic,
                        "qos", qos,
                        "stream_id", null,
                        "stream_error", e.getMessage()
                ));
            }
        } catch (Exception e) {
            log.error("mqtt-bridge: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/messages/topic/{topic}")
    public ResponseEntity<?> byTopic(@PathVariable String topic,
                                     @RequestParam(defaultValue = "50") int limit) {
        try {
            if (limit <= 0 || limit > 500) limit = 50;
            List<MqttMessage> rows = messages.findByTopicOrderByIdDesc(topic, PageRequest.of(0, limit));
            return ResponseEntity.ok(rows.stream().map(this::msgMap).collect(Collectors.toList()));
        } catch (Exception e) {
            log.error("mqtt-bridge: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @PostMapping("/subscriptions")
    public ResponseEntity<?> subscribe(@RequestBody Map<String, Object> body) {
        try {
            String clientId = (String) body.get("client_id");
            String pattern = (String) body.get("topic_pattern");
            if (clientId == null || pattern == null) {
                return ResponseEntity.badRequest().body(Map.of("error", "client_id, topic_pattern required"));
            }
            Subscription s = new Subscription();
            s.setClientId(clientId);
            s.setTopicPattern(pattern);
            s.setSubscribedAt(OffsetDateTime.now());
            subscriptions.save(s);
            return ResponseEntity.status(201).body(subMap(s));
        } catch (Exception e) {
            log.error("mqtt-bridge: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @GetMapping("/subscriptions/{clientId}")
    public ResponseEntity<?> listSubs(@PathVariable String clientId) {
        try {
            List<Subscription> rows = subscriptions.findByClientIdOrderByIdDesc(clientId);
            return ResponseEntity.ok(rows.stream().map(this::subMap).collect(Collectors.toList()));
        } catch (Exception e) {
            log.error("mqtt-bridge: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    @DeleteMapping("/subscriptions/{id}")
    public ResponseEntity<?> unsubscribe(@PathVariable Long id) {
        try {
            if (!subscriptions.existsById(id)) {
                return ResponseEntity.status(404).body(Map.of("error", "not found"));
            }
            subscriptions.deleteById(id);
            return ResponseEntity.ok(Map.of("deleted", id));
        } catch (Exception e) {
            log.error("mqtt-bridge: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "internal error"));
        }
    }

    private Map<String, Object> msgMap(MqttMessage m) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", m.getId());
        map.put("topic", m.getTopic());
        map.put("payload", m.getPayload());
        map.put("qos", m.getQos());
        map.put("received_at", m.getReceivedAt() == null ? null : m.getReceivedAt().toString());
        return map;
    }

    private Map<String, Object> subMap(Subscription s) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", s.getId());
        map.put("client_id", s.getClientId());
        map.put("topic_pattern", s.getTopicPattern());
        map.put("subscribed_at", s.getSubscribedAt() == null ? null : s.getSubscribedAt().toString());
        return map;
    }
}
