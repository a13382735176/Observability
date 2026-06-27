package com.vibe.account;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "accounts")
public class Account {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String userId;
    private String accountType;
    private String currency;
    private Long balanceCents = 0L;
    private OffsetDateTime createdAt = OffsetDateTime.now();

    public Account() {}
    public Account(String userId, String accountType, String currency) {
        this.userId = userId;
        this.accountType = accountType;
        this.currency = currency;
    }

    public Long getId() { return id; }
    public String getUserId() { return userId; }
    public String getAccountType() { return accountType; }
    public String getCurrency() { return currency; }
    public Long getBalanceCents() { return balanceCents; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
