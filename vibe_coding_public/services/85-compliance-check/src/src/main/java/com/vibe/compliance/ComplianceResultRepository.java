package com.vibe.compliance;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
public interface ComplianceResultRepository extends JpaRepository<ComplianceResult,Integer> {
    List<ComplianceResult> findByEntityId(String entityId);
}
