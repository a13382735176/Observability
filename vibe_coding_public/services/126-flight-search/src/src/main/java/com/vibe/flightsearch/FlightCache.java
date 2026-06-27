package com.vibe.flightsearch;

import jakarta.persistence.*;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Entity
@Table(name = "flight_cache",
       uniqueConstraints = @UniqueConstraint(columnNames = {"origin", "dest", "fly_date"}))
public class FlightCache {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String origin;

    @Column(nullable = false)
    private String dest;

    @Column(name = "fly_date", nullable = false)
    private LocalDate flyDate;

    @Column(columnDefinition = "text")
    private String data;

    @Column(name = "cached_at")
    private OffsetDateTime cachedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getOrigin() { return origin; }
    public void setOrigin(String origin) { this.origin = origin; }
    public String getDest() { return dest; }
    public void setDest(String dest) { this.dest = dest; }
    public LocalDate getFlyDate() { return flyDate; }
    public void setFlyDate(LocalDate flyDate) { this.flyDate = flyDate; }
    public String getData() { return data; }
    public void setData(String data) { this.data = data; }
    public OffsetDateTime getCachedAt() { return cachedAt; }
    public void setCachedAt(OffsetDateTime cachedAt) { this.cachedAt = cachedAt; }
}
