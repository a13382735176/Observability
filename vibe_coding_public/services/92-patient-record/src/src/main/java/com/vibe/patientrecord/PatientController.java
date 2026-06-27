package com.vibe.patientrecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

@RestController
public class PatientController {
    private static final Logger log = LoggerFactory.getLogger(PatientController.class);
    @Autowired private PatientRepository repo;

    @GetMapping("/healthz")
    public Map<String,String> healthz() { return Map.of("status","ok","service","patient-record"); }

    @PostMapping("/patients")
    public ResponseEntity<?> create(@RequestBody Map<String,Object> body) {
        try {
            Patient p = new Patient();
            p.setName((String) body.get("name"));
            p.setDob(LocalDate.parse((String) body.get("dob_str")));
            p.setBloodType((String) body.get("blood_type"));
            @SuppressWarnings("unchecked")
            List<String> allergies = (List<String>) body.getOrDefault("allergies", List.of());
            p.setAllergies(allergies);
            Patient saved = repo.save(p);
            return ResponseEntity.status(201).body(saved);
        } catch (Exception e) {
            log.error("patient-record: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }

    @GetMapping("/patients/{id}")
    public ResponseEntity<?> get(@PathVariable Integer id) {
        try {
            return repo.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
        } catch (Exception e) {
            log.error("patient-record: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }

    @PutMapping("/patients/{id}/allergies")
    public ResponseEntity<?> updateAllergies(@PathVariable Integer id, @RequestBody Map<String,Object> body) {
        try {
            Patient p = repo.findById(id).orElse(null);
            if (p == null) return ResponseEntity.notFound().build();
            @SuppressWarnings("unchecked")
            List<String> allergies = (List<String>) body.get("allergies");
            p.setAllergies(allergies);
            return ResponseEntity.ok(repo.save(p));
        } catch (Exception e) {
            log.error("patient-record: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }
}
