package com.vibe.policyengineskill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalErrorHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalErrorHandler.class);

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handle(Exception ex) {
        log.error("request_failed service={} outcome={} error_type={}",
                serviceName(), "failure", ex.getClass().getSimpleName());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "error");
        body.put("service", serviceName());
        body.put("message", "internal server error");
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
    }

    private static String serviceName() {
        return System.getenv().getOrDefault("APP_NAME", "policy-engine-skill");
    }
}
