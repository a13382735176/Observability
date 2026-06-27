package com.vibe.mqttbridge;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SubscriptionRepository extends JpaRepository<Subscription, Long> {
    List<Subscription> findByClientIdOrderByIdDesc(String clientId);
}
