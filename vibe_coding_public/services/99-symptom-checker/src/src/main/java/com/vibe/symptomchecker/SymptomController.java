package com.vibe.symptomchecker;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;
import java.util.stream.Collectors;

@RestController
public class SymptomController {
    private static final Logger log = LoggerFactory.getLogger(SymptomController.class);
    @Autowired private StringRedisTemplate redis;
    private final ObjectMapper mapper = new ObjectMapper();

    @GetMapping("/healthz")
    public Map<String,String> healthz() { return Map.of("status","ok","service","symptom-checker"); }

    @PutMapping("/conditions")
    public ResponseEntity<?> putCondition(@RequestBody Map<String,Object> body) {
        try {
            String name = (String) body.get("condition_name");
            @SuppressWarnings("unchecked")
            List<String> symptoms = (List<String>) body.get("symptoms");
            String json = mapper.writeValueAsString(symptoms);
            redis.opsForHash().put("symptoms:" + name, "data", json);
            return ResponseEntity.ok(Map.of("condition_name", name, "symptoms", symptoms));
        } catch (Exception e) {
            log.error("symptom-checker: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","error"));
        }
    }

    @GetMapping("/conditions")
    public ResponseEntity<?> listConditions() {
        try {
            Set<String> keys = redis.keys("symptoms:*");
            if (keys == null) return ResponseEntity.ok(List.of());
            List<String> names = keys.stream()
                .map(k -> k.replace("symptoms:", ""))
                .collect(Collectors.toList());
            return ResponseEntity.ok(names);
        } catch (Exception e) {
            log.error("symptom-checker: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","error"));
        }
    }

    @PostMapping("/assess")
    public ResponseEntity<?> assess(@RequestBody Map<String,Object> body) {
        try {
            @SuppressWarnings("unchecked")
            List<String> inputSymptoms = (List<String>) body.get("symptoms");
            Set<String> keys = redis.keys("symptoms:*");
            if (keys == null) return ResponseEntity.ok(List.of());
            List<Map<String,Object>> matches = new ArrayList<>();
            for (String key : keys) {
                try {
                    String data = (String) redis.opsForHash().get(key, "data");
                    if (data == null) continue;
                    @SuppressWarnings("unchecked")
                    List<String> condSymptoms = mapper.readValue(data, List.class);
                    List<String> overlap = condSymptoms.stream()
                        .filter(inputSymptoms::contains).collect(Collectors.toList());
                    if (!overlap.isEmpty()) {
                        String condName = key.replace("symptoms:", "");
                        matches.add(Map.of("condition", condName, "matched_symptoms", overlap));
                    }
                } catch (Exception e) {
                    log.error("symptom-checker: {}", e.getMessage(), e);
                }
            }
            return ResponseEntity.ok(matches);
        } catch (Exception e) {
            log.error("symptom-checker: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","error"));
        }
    }
}
