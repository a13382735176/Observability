package com.vibe.devicereg;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import javax.sql.DataSource;

@SpringBootApplication
public class Application {
    private static final Logger log = LoggerFactory.getLogger("device-registry");

    public static void main(String[] args) { SpringApplication.run(Application.class, args); }

    @Bean
    CommandLineRunner initDb(DataSource ds) {
        return args -> {
            try (var conn = ds.getConnection(); var st = conn.createStatement()) {
                st.execute("CREATE TABLE IF NOT EXISTS devices(id SERIAL PRIMARY KEY," +
                    "device_id TEXT UNIQUE NOT NULL, type TEXT NOT NULL," +
                    "firmware_version TEXT, status TEXT DEFAULT 'online'," +
                    "registered_at TIMESTAMPTZ DEFAULT NOW())");
                log.info("device-registry: db init ok");
            } catch (Exception e) {
                log.error("device-registry: db init failed: {}", e.getMessage(), e);
            }
        };
    }
}
