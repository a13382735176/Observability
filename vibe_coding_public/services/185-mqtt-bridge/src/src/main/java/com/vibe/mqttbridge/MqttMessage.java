package com.vibe.mqttbridge;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "mqtt_messages")
public class MqttMessage {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String topic;

    @Column(columnDefinition = "text")
    private String payload;

    @Column(nullable = false)
    private int qos;

    @Column(name = "received_at", nullable = false)
    private OffsetDateTime receivedAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getTopic() { return topic; }
    public void setTopic(String topic) { this.topic = topic; }
    public String getPayload() { return payload; }
    public void setPayload(String payload) { this.payload = payload; }
    public int getQos() { return qos; }
    public void setQos(int qos) { this.qos = qos; }
    public OffsetDateTime getReceivedAt() { return receivedAt; }
    public void setReceivedAt(OffsetDateTime receivedAt) { this.receivedAt = receivedAt; }
}
