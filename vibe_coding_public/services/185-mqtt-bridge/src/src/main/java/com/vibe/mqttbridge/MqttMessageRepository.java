package com.vibe.mqttbridge;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface MqttMessageRepository extends JpaRepository<MqttMessage, Long> {
    List<MqttMessage> findByTopicOrderByIdDesc(String topic, Pageable pageable);
}
