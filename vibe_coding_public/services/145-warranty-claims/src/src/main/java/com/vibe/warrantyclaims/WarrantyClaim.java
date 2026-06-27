package com.vibe.warrantyclaims;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "warranty_claims")
public class WarrantyClaim {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id")
    private String productId;

    @Column(name = "user_id")
    private String userId;

    @Column(name = "defect_description", columnDefinition = "text")
    private String defectDescription;

    @Column(name = "status")
    private String status = "open";

    @Column(name = "resolution", columnDefinition = "text")
    private String resolution;

    @Column(name = "created_at")
    private OffsetDateTime createdAt;

    @Column(name = "updated_at")
    private OffsetDateTime updatedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getProductId() { return productId; }
    public void setProductId(String productId) { this.productId = productId; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getDefectDescription() { return defectDescription; }
    public void setDefectDescription(String defectDescription) { this.defectDescription = defectDescription; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getResolution() { return resolution; }
    public void setResolution(String resolution) { this.resolution = resolution; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }
    public OffsetDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(OffsetDateTime updatedAt) { this.updatedAt = updatedAt; }
}
