package com.vibe.compliance;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.Map;
@RestController
public class ComplianceController {
    private static final Logger log = LoggerFactory.getLogger(ComplianceController.class);
    @Autowired private ComplianceRuleRepository ruleRepo;
    @Autowired private ComplianceResultRepository resultRepo;

    @GetMapping("/healthz")
    public Map<String,String> healthz(){ return Map.of("status","ok","service","compliance-check"); }

    @PostMapping("/check")
    public ResponseEntity<?> check(@RequestBody Map<String,Object> body){
        try {
            String entityId=(String)body.get("entity_id");
            String checkType=(String)body.getOrDefault("check_type","kyc");
            boolean passed=Math.random()>0.1;
            ComplianceResult r=new ComplianceResult();
            r.setEntityId(entityId); r.setRuleName(checkType); r.setPassed(passed);
            resultRepo.save(r);
            return ResponseEntity.status(201).body(r);
        } catch(Exception e){
            log.error("compliance-check: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }

    @GetMapping("/results/{entity_id}")
    public ResponseEntity<?> getResults(@PathVariable String entity_id){
        try { return ResponseEntity.ok(resultRepo.findByEntityId(entity_id)); }
        catch(Exception e){
            log.error("compliance-check: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }

    @PostMapping("/rules")
    public ResponseEntity<?> addRule(@RequestBody Map<String,Object> body){
        try {
            ComplianceRule rule=new ComplianceRule();
            rule.setRuleName((String)body.get("rule_name"));
            rule.setDescription((String)body.getOrDefault("description",""));
            Object th=body.get("threshold");
            if(th!=null) rule.setThresholdValue(((Number)th).doubleValue());
            ruleRepo.save(rule);
            return ResponseEntity.status(201).body(rule);
        } catch(Exception e){
            log.error("compliance-check: {}", e.getMessage(), e);
            return ResponseEntity.status(503).body(Map.of("error","db error"));
        }
    }
}
