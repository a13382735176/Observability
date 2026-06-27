package com.vibe.promoengine;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "promos")
public class Promo {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private String code;

    @Column(name = "discount_pct", nullable = false)
    private Integer discountPct;

    @Column(name = "valid_until")
    private OffsetDateTime validUntil;

    @Column(nullable = false)
    private Boolean active = true;

    @Column(name = "created_at")
    private OffsetDateTime createdAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getCode() { return code; }
    public void setCode(String code) { this.code = code; }
    public Integer getDiscountPct() { return discountPct; }
    public void setDiscountPct(Integer discountPct) { this.discountPct = discountPct; }
    public OffsetDateTime getValidUntil() { return validUntil; }
    public void setValidUntil(OffsetDateTime validUntil) { this.validUntil = validUntil; }
    public Boolean getActive() { return active; }
    public void setActive(Boolean active) { this.active = active; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }
}
