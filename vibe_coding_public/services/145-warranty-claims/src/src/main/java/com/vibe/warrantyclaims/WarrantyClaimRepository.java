package com.vibe.warrantyclaims;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface WarrantyClaimRepository extends JpaRepository<WarrantyClaim, Long> {
    List<WarrantyClaim> findTop20ByUserIdOrderByIdDesc(String userId);
}
