package com.vibe;

import jakarta.persistence.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.time.LocalDate;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@SpringBootApplication
@EnableJpaRepositories(considerNestedRepositories = true)
public class App {
    private static final Logger log = LoggerFactory.getLogger(App.class);
    private static final String SERVICE = "visa-application";

    public static void main(String[] args) {
        SpringApplication.run(App.class, args);
    }

    @Entity
    @Table(name = "visa_applications")
    public static class VisaApplication {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        public Long id;

        @Column(name = "user_id")
        public String userId;

        @Column(name = "destination_country")
        public String destinationCountry;

        @Column(name = "travel_date")
        public LocalDate travelDate;

        public String purpose;

        public String status = "pending";

        @Column(name = "submitted_at")
        public Instant submittedAt = Instant.now();
    }

    public interface VisaRepo extends JpaRepository<VisaApplication, Long> {
        List<VisaApplication> findByUserIdOrderByIdDesc(String userId);
    }

    @RestController
    public static class Routes {
        private final VisaRepo repo;

        public Routes(VisaRepo repo) {
            this.repo = repo;
        }

        @GetMapping("/healthz")
        public Map<String, String> healthz() {
            Map<String, String> m = new HashMap<>();
            m.put("status", "ok");
            m.put("service", SERVICE);
            return m;
        }

        @PostMapping("/applications")
        public Object create(@RequestBody Map<String, Object> body) {
            try {
                VisaApplication v = new VisaApplication();
                v.userId = strOf(body.get("user_id"));
                v.destinationCountry = strOf(body.get("destination_country"));
                String td = strOf(body.get("travel_date"));
                if (td != null && !td.isEmpty()) {
                    v.travelDate = LocalDate.parse(td);
                }
                v.purpose = strOf(body.get("purpose"));
                v.status = "pending";
                v.submittedAt = Instant.now();
                return repo.save(v);
            } catch (Exception e) {
                log.error("visa-application: create: {}", e.getMessage(), e);
                return Map.of("error", e.getMessage());
            }
        }

        @GetMapping("/applications/{userId}")
        public Object byUser(@PathVariable String userId) {
            try {
                return repo.findByUserIdOrderByIdDesc(userId);
            } catch (Exception e) {
                log.error("visa-application: byUser: {}", e.getMessage(), e);
                return Map.of("error", e.getMessage());
            }
        }

        @PutMapping("/applications/{id}/status")
        public Object updateStatus(@PathVariable Long id, @RequestBody Map<String, Object> body) {
            try {
                Optional<VisaApplication> opt = repo.findById(id);
                if (opt.isEmpty()) {
                    return Map.of("error", "not found");
                }
                String status = strOf(body.get("status"));
                if (!"pending".equals(status) && !"approved".equals(status) && !"rejected".equals(status)) {
                    return Map.of("error", "invalid status");
                }
                VisaApplication v = opt.get();
                v.status = status;
                return repo.save(v);
            } catch (Exception e) {
                log.error("visa-application: updateStatus: {}", e.getMessage(), e);
                return Map.of("error", e.getMessage());
            }
        }

        @GetMapping("/applications")
        public Object listAll() {
            try {
                return repo.findAll();
            } catch (Exception e) {
                log.error("visa-application: listAll: {}", e.getMessage(), e);
                return Map.of("error", e.getMessage());
            }
        }

        private static String strOf(Object o) {
            return o == null ? null : o.toString();
        }
    }
}
