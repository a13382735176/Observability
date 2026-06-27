package com.vibe.policyengineskill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;

@SpringBootApplication
public class PolicyEngineSkillApplication {
    private static final Logger log = LoggerFactory.getLogger(PolicyEngineSkillApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(PolicyEngineSkillApplication.class, args);
    }

    @EventListener(ApplicationReadyEvent.class)
    public void onReady() {
        log.info("service_ready service={} port={}", serviceName(), 8080);
    }

    private String serviceName() {
        return System.getenv().getOrDefault("APP_NAME", "policy-engine-skill");
    }
}
