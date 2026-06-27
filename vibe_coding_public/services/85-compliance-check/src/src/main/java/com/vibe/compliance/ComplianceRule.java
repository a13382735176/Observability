package com.vibe.compliance;
import jakarta.persistence.*;
@Entity @Table(name="compliance_rules")
public class ComplianceRule {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Integer id;
    @Column(unique=true) private String ruleName;
    private String description;
    private Double thresholdValue;
    public Integer getId(){return id;}
    public String getRuleName(){return ruleName;}
    public void setRuleName(String v){this.ruleName=v;}
    public String getDescription(){return description;}
    public void setDescription(String v){this.description=v;}
    public Double getThresholdValue(){return thresholdValue;}
    public void setThresholdValue(Double v){this.thresholdValue=v;}
}
