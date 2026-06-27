package com.vibe.ledger;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;
public interface LedgerRepository extends JpaRepository<LedgerEntry, Long> {
    @Query("SELECT e FROM LedgerEntry e WHERE e.debitAccount = :account OR e.creditAccount = :account ORDER BY e.ts DESC")
    List<LedgerEntry> findByAccount(String account);
    @Query("SELECT e.debitAccount, SUM(e.amountCents) FROM LedgerEntry e GROUP BY e.debitAccount")
    List<Object[]> sumByDebit();
}
