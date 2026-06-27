package com.vibe.comment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import javax.sql.DataSource;

@SpringBootApplication
public class Application {
    private static final Logger log = LoggerFactory.getLogger("comment-service");

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }

    @Bean
    CommandLineRunner initDb(DataSource ds) {
        return args -> {
            try (var conn = ds.getConnection(); var st = conn.createStatement()) {
                st.execute("CREATE TABLE IF NOT EXISTS comments(" +
                    "id SERIAL PRIMARY KEY, post_id INT NOT NULL," +
                    "user_id TEXT NOT NULL, text TEXT NOT NULL," +
                    "created_at TIMESTAMPTZ DEFAULT NOW())");
                log.info("comment-service: db init ok");
            } catch (Exception e) {
                log.error("comment-service: db init failed: {}", e.getMessage(), e);
            }
        };
    }
}
