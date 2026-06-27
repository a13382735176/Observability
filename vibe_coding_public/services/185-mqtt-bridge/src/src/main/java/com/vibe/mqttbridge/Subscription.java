package com.vibe.mqttbridge;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "subscriptions")
public class Subscription {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "client_id", nullable = false)
    private String clientId;

    @Column(name = "topic_pattern", nullable = false)
    private String topicPattern;

    @Column(name = "subscribed_at", nullable = false)
    private OffsetDateTime subscribedAt = OffsetDateTime.now();

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getClientId() { return clientId; }
    public void setClientId(String clientId) { this.clientId = clientId; }
    public String getTopicPattern() { return topicPattern; }
    public void setTopicPattern(String topicPattern) { this.topicPattern = topicPattern; }
    public OffsetDateTime getSubscribedAt() { return subscribedAt; }
    public void setSubscribedAt(OffsetDateTime subscribedAt) { this.subscribedAt = subscribedAt; }
}
