package com.vibe.story;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import javax.sql.DataSource;

@SpringBootApplication
public class Application {
    private static final Logger log = LoggerFactory.getLogger("story-service");

    public static void main(String[] args) { SpringApplication.run(Application.class, args); }

    @Bean
    CommandLineRunner initDb(DataSource ds) {
        return args -> {
            try (var conn = ds.getConnection(); var st = conn.createStatement()) {
                st.execute("CREATE TABLE IF NOT EXISTS stories(id SERIAL PRIMARY KEY," +
                    "user_id TEXT NOT NULL, media_url TEXT NOT NULL," +
                    "expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())");
                log.info("story-service: db init ok");
            } catch (Exception e) {
                log.error("story-service: db init failed: {}", e.getMessage(), e);
            }
        };
    }
}
