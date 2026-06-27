package com.vibe.promoengine;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface PromoRepository extends JpaRepository<Promo, Long> {
    Optional<Promo> findByCodeAndActiveTrue(String code);
    Optional<Promo> findByCode(String code);
    List<Promo> findByActiveTrue();
}
