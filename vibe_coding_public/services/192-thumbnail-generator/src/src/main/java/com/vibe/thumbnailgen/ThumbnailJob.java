package com.vibe.thumbnailgen;

import jakarta.persistence.*;
import java.time.OffsetDateTime;

@Entity
@Table(name = "thumbnail_jobs")
public class ThumbnailJob {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "source_image_url", columnDefinition = "text")
    private String sourceImageUrl;

    @Column(name = "size")
    private Integer size;

    @Column(name = "thumbnail_url", columnDefinition = "text")
    private String thumbnailUrl;

    @Column(name = "status")
    private String status = "pending";

    @Column(name = "created_at")
    private OffsetDateTime createdAt = OffsetDateTime.now();

    @Column(name = "completed_at")
    private OffsetDateTime completedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSourceImageUrl() { return sourceImageUrl; }
    public void setSourceImageUrl(String s) { this.sourceImageUrl = s; }
    public Integer getSize() { return size; }
    public void setSize(Integer s) { this.size = s; }
    public String getThumbnailUrl() { return thumbnailUrl; }
    public void setThumbnailUrl(String s) { this.thumbnailUrl = s; }
    public String getStatus() { return status; }
    public void setStatus(String s) { this.status = s; }
    public OffsetDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(OffsetDateTime t) { this.createdAt = t; }
    public OffsetDateTime getCompletedAt() { return completedAt; }
    public void setCompletedAt(OffsetDateTime t) { this.completedAt = t; }
}
