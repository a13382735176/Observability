package com.vibe.ledger;
import jakarta.persistence.*;
import java.time.OffsetDateTime;
@Entity @Table(name = "ledger_entries")
public class LedgerEntry {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    private String debitAccount;
    private String creditAccount;
    private Long amountCents;
    private String description;
    private OffsetDateTime ts = OffsetDateTime.now();
    public LedgerEntry() {}
    public LedgerEntry(String debit, String credit, Long amount, String desc) {
        this.debitAccount = debit; this.creditAccount = credit;
        this.amountCents = amount; this.description = desc;
    }
    public Long getId() { return id; }
    public String getDebitAccount() { return debitAccount; }
    public String getCreditAccount() { return creditAccount; }
    public Long getAmountCents() { return amountCents; }
    public String getDescription() { return description; }
    public OffsetDateTime getTs() { return ts; }
}
