package com.vibe.policyengineskill;

import org.springframework.stereotype.Component;

@Component
public class RedisSettings {
    private final String host;
    private final int port;

    public RedisSettings() {
        this.host = valueOrDefault("REDIS_CACHE_HOST", "redis-cache");
        this.port = parsePort(valueOrDefault("REDIS_CACHE_PORT", "6379"));
    }

    public String host() {
        return host;
    }

    public int port() {
        return port;
    }

    private static String valueOrDefault(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static int parsePort(String value) {
        try {
            int parsed = Integer.parseInt(value);
            if (parsed > 0 && parsed <= 65535) {
                return parsed;
            }
        } catch (NumberFormatException ignored) {
            // Fall through to the contract default.
        }
        return 6379;
    }
}
