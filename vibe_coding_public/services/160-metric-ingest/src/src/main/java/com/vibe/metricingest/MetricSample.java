package com.vibe.metricingest;

import io.hypersistence.utils.hibernate.type.json.JsonBinaryType;
import jakarta.persistence.*;
import org.hibernate.annotations.Type;

import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.Map;

@Entity
@Table(name = "metric_samples", indexes = {
        @Index(name = "metric_samples_name_ts_idx", columnList = "name, ts")
})
public class MetricSample {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private Double value;

    @Type(JsonBinaryType.class)
    @Column(columnDefinition = "jsonb")
    private Map<String, String> tags = new HashMap<>();

    @Column(nullable = false)
    private OffsetDateTime ts;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public Double getValue() { return value; }
    public void setValue(Double value) { this.value = value; }
    public Map<String, String> getTags() { return tags; }
    public void setTags(Map<String, String> tags) { this.tags = tags; }
    public OffsetDateTime getTs() { return ts; }
    public void setTs(OffsetDateTime ts) { this.ts = ts; }
}
