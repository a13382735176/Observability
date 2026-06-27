package com.vibe.mqttbridge;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ApplicationListener;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.stereotype.Component;

@SpringBootApplication
public class MqttBridgeSkillApplication {
    private static final Logger log = LoggerFactory.getLogger(MqttBridgeSkillApplication.class);

    public static void main(String[] args) {
        log.info("service_starting service={} port={}", Env.appName(), 8080);
        SpringApplication.run(MqttBridgeSkillApplication.class, args);
        log.info("service_started service={} port={}", Env.appName(), 8080);
    }
}

@Component
class ShutdownLogger implements ApplicationListener<ContextClosedEvent> {
    private static final Logger log = LoggerFactory.getLogger(ShutdownLogger.class);

    @Override
    public void onApplicationEvent(ContextClosedEvent event) {
        log.info("service_stopping service={}", Env.appName());
    }
}
