package com.vibe.ledger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;
@RestController
public class LedgerController {
    private static final Logger log = LoggerFactory.getLogger(LedgerController.class);
    @Autowired private LedgerRepository repo;

    @GetMapping("/healthz")
    public Map<String, String> healthz() { return Map.of("status", "ok", "service", "ledger-service"); }

    @PostMapping("/entries")
    public ResponseEntity<?> addEntry(@RequestBody Map<String, Object> body) {
        try {
            String debit = (String) body.get("debit_account");
            String credit = (String) body.get("credit_account");
            Long amount = ((Number) body.get("amount_cents")).longValue();
            String desc = (String) body.getOrDefault("description", "");
            LedgerEntry e = new LedgerEntry(debit, credit, amount, desc);
            repo.save(e);
            return ResponseEntity.status(201).body(e);
        } catch (Exception e) {
            log.error("ledger-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/entries/{account}")
    public ResponseEntity<?> getEntries(@PathVariable String account) {
        try {
            return ResponseEntity.ok(repo.findByAccount(account));
        } catch (Exception e) {
            log.error("ledger-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }

    @GetMapping("/balance-sheet")
    public ResponseEntity<?> balanceSheet() {
        try {
            List<Object[]> rows = repo.sumByDebit();
            List<Map<String, Object>> result = new ArrayList<>();
            for (Object[] row : rows) {
                result.add(Map.of("account", row[0], "total_cents", row[1]));
            }
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            log.error("ledger-service: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error", "db error"));
        }
    }
}
