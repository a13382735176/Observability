package com.vibe.patientrecord;
import jakarta.persistence.*;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "patients")
public class Patient {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;
    private String name;
    private LocalDate dob;
    @Column(name = "blood_type")
    private String bloodType;
    @Column(name = "allergies", columnDefinition = "jsonb")
    @JdbcTypeCode(SqlTypes.JSON)
    private List<String> allergies = new ArrayList<>();
    @Column(name = "created_at", insertable = false, updatable = false)
    private OffsetDateTime createdAt;

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public LocalDate getDob() { return dob; }
    public void setDob(LocalDate dob) { this.dob = dob; }
    public String getBloodType() { return bloodType; }
    public void setBloodType(String bloodType) { this.bloodType = bloodType; }
    public List<String> getAllergies() { return allergies; }
    public void setAllergies(List<String> allergies) { this.allergies = allergies; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
}
