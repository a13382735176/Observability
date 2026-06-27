package com.vibe.mqttbridge;

import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisConnectionException;
import io.lettuce.core.api.StatefulRedisConnection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Duration;

@Component
class RedisStreamClient implements AutoCloseable {
    private static final Logger log = LoggerFactory.getLogger(RedisStreamClient.class);
    private final RedisClient client;
    private final String host;
    private final int port;

    RedisStreamClient() {
        this.host = Env.redisHost();
        this.port = Env.redisPort();
        this.client = RedisClient.create("redis://" + host + ":" + port);
        this.client.setDefaultTimeout(Duration.ofSeconds(2));
        log.info("dependency_configured service={} dependency=redis-stream host={} port={} stream={}",
                Env.appName(), host, port, Env.STREAM_NAME);
    }

    RedisStatus check() {
        long start = System.nanoTime();
        try (StatefulRedisConnection<String, String> connection = client.connect()) {
            String pong = connection.sync().ping();
            long latencyMs = elapsedMillis(start);
            boolean up = "PONG".equalsIgnoreCase(pong);
            log.info("dependency_check service={} dependency=redis-stream operation=ping status={} latency_ms={} stream={}",
                    Env.appName(), up ? "up" : "unexpected", latencyMs, Env.STREAM_NAME);
            return new RedisStatus(up ? "up" : "unexpected", latencyMs, null);
        } catch (RedisConnectionException ex) {
            long latencyMs = elapsedMillis(start);
            log.warn("dependency_check service={} dependency=redis-stream operation=ping status=down latency_ms={} error={}",
                    Env.appName(), latencyMs, ex.getClass().getSimpleName());
            return new RedisStatus("down", latencyMs, ex.getClass().getSimpleName());
        } catch (RuntimeException ex) {
            long latencyMs = elapsedMillis(start);
            log.warn("dependency_check service={} dependency=redis-stream operation=ping status=error latency_ms={} error={}",
                    Env.appName(), latencyMs, ex.getClass().getSimpleName());
            return new RedisStatus("error", latencyMs, ex.getClass().getSimpleName());
        }
    }

    private static long elapsedMillis(long start) {
        return Duration.ofNanos(System.nanoTime() - start).toMillis();
    }

    @Override
    public void close() {
        client.shutdown();
    }

    record RedisStatus(String status, long latencyMs, String error) {
    }
}
