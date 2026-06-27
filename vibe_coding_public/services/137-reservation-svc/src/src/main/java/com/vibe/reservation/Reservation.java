package com.vibe.reservation;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "reservations")
public class Reservation {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "restaurant_id", nullable = false)
    private String restaurantId;

    @Column(name = "user_id", nullable = false)
    private String userId;

    @Column(name = "party_size", nullable = false)
    private int partySize;

    @Column(name = "reservation_time", nullable = false)
    private OffsetDateTime reservationTime;

    @Column(nullable = false)
    private String status = "confirmed";

    @Column(name = "created_at", nullable = false)
    private OffsetDateTime createdAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getRestaurantId() { return restaurantId; }
    public void setRestaurantId(String restaurantId) { this.restaurantId = restaurantId; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public int getPartySize() { return partySize; }
    public void setPartySize(int partySize) { this.partySize = partySize; }
    public OffsetDateTime getReservationTime() { return reservationTime; }
    public void setReservationTime(OffsetDateTime reservationTime) { this.reservationTime = reservationTime; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime createdAt) { this.createdAt = createdAt; }
}
