package com.vibe.taskrunner;

import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface TaskRepository extends JpaRepository<Task, Long> {
    @Query("SELECT t FROM Task t WHERE t.status = ?1 ORDER BY t.id DESC")
    List<Task> findByStatus(String status, Pageable pageable);

    @Query("SELECT t FROM Task t ORDER BY t.id DESC")
    List<Task> findAllRecent(Pageable pageable);

    default List<Task> listByStatus(String status, int limit) {
        return findByStatus(status, PageRequest.of(0, limit));
    }

    default List<Task> listRecent(int limit) {
        return findAllRecent(PageRequest.of(0, limit));
    }
}
