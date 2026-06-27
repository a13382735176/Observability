package com.vibe.promoengine;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "promo_redemptions")
public class PromoRedemption {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "promo_code")
    private String promoCode;

    @Column(name = "user_id")
    private String userId;

    @Column(name = "redeemed_at")
    private OffsetDateTime redeemedAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getPromoCode() { return promoCode; }
    public void setPromoCode(String promoCode) { this.promoCode = promoCode; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public OffsetDateTime getRedeemedAt() { return redeemedAt; }
    public void setRedeemedAt(OffsetDateTime redeemedAt) { this.redeemedAt = redeemedAt; }
}
