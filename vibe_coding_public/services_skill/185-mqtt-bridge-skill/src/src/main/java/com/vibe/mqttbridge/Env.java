package com.vibe.mqttbridge;

final class Env {
    static final String STREAM_NAME = "events:mqtt";

    private Env() {
    }

    static String appName() {
        return getenv("APP_NAME", "mqtt-bridge-skill");
    }

    static String redisHost() {
        return getenv("REDIS_STREAM_HOST", "redis-stream");
    }

    static int redisPort() {
        String value = getenv("REDIS_STREAM_PORT", "6379");
        try {
            return Integer.parseInt(value);
        } catch (NumberFormatException ex) {
            return 6379;
        }
    }

    private static String getenv(String name, String defaultValue) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}
