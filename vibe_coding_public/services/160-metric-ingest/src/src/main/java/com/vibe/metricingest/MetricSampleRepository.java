package com.vibe.metricingest;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

public interface MetricSampleRepository extends JpaRepository<MetricSample, Long> {
    Optional<MetricSample> findFirstByNameOrderByTsDesc(String name);

    @Query("SELECT m FROM MetricSample m WHERE m.name = :name AND m.ts BETWEEN :from AND :to ORDER BY m.ts ASC")
    List<MetricSample> findSeries(@Param("name") String name,
                                  @Param("from") OffsetDateTime from,
                                  @Param("to") OffsetDateTime to);
}
