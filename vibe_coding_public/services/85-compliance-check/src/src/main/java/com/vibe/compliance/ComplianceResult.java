package com.vibe.compliance;
import jakarta.persistence.*;
import java.time.OffsetDateTime;
@Entity @Table(name="compliance_results")
public class ComplianceResult {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Integer id;
    private String entityId;
    private String ruleName;
    private Boolean passed;
    private OffsetDateTime checkedAt;
    @PrePersist void prePersist(){checkedAt=OffsetDateTime.now();}
    public Integer getId(){return id;}
    public String getEntityId(){return entityId;}
    public void setEntityId(String v){this.entityId=v;}
    public String getRuleName(){return ruleName;}
    public void setRuleName(String v){this.ruleName=v;}
    public Boolean getPassed(){return passed;}
    public void setPassed(Boolean v){this.passed=v;}
    public OffsetDateTime getCheckedAt(){return checkedAt;}
}
