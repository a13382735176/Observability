package com.vibe.reservation;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.OffsetDateTime;
import java.util.List;

public interface ReservationRepository extends JpaRepository<Reservation, Long> {
    List<Reservation> findByUserIdOrderByIdDesc(String userId);

    @Query("SELECT r FROM Reservation r WHERE r.restaurantId = :rid AND r.reservationTime >= :start AND r.reservationTime < :end ORDER BY r.reservationTime ASC")
    List<Reservation> findByRestaurantAndDay(@Param("rid") String restaurantId,
                                             @Param("start") OffsetDateTime start,
                                             @Param("end") OffsetDateTime end);
}
