package com.vibe.policyengine;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "policies")
public class Policy {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String name;

    @Column(nullable = false)
    private String effect;

    @Column(name = "resource_pattern", nullable = false)
    private String resourcePattern;

    @Column(name = "action_pattern", nullable = false)
    private String actionPattern;

    @Column(name = "principal_pattern", nullable = false)
    private String principalPattern;

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getEffect() { return effect; }
    public void setEffect(String effect) { this.effect = effect; }
    public String getResourcePattern() { return resourcePattern; }
    public void setResourcePattern(String resourcePattern) { this.resourcePattern = resourcePattern; }
    public String getActionPattern() { return actionPattern; }
    public void setActionPattern(String actionPattern) { this.actionPattern = actionPattern; }
    public String getPrincipalPattern() { return principalPattern; }
    public void setPrincipalPattern(String principalPattern) { this.principalPattern = principalPattern; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }
}
