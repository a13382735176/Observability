package com.vibe.thumbnailgen;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ThumbnailJobRepository extends JpaRepository<ThumbnailJob, Long> {
    List<ThumbnailJob> findBySourceImageUrl(String sourceImageUrl);
}
