package com.vibe.flightsearch;

import org.springframework.data.jpa.repository.JpaRepository;
import java.time.LocalDate;
import java.util.Optional;

public interface FlightCacheRepository extends JpaRepository<FlightCache, Long> {
    Optional<FlightCache> findByOriginAndDestAndFlyDate(String origin, String dest, LocalDate flyDate);
}
