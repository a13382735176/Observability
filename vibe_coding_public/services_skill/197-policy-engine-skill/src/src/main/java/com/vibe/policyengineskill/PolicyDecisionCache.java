package com.vibe.policyengineskill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;

import java.time.Duration;
import java.util.Optional;

@Component
public class PolicyDecisionCache implements AutoCloseable {
    private static final Logger log = LoggerFactory.getLogger(PolicyDecisionCache.class);
    private static final int DEFAULT_TTL_SECONDS = 300;

    private final RedisSettings settings;
    private final JedisPool pool;

    public PolicyDecisionCache(RedisSettings settings) {
        this.settings = settings;
        JedisPoolConfig config = new JedisPoolConfig();
        config.setMaxTotal(8);
        config.setMaxIdle(4);
        config.setMinIdle(0);
        config.setTestOnBorrow(true);
        this.pool = new JedisPool(config, settings.host(), settings.port(), 1500);
        log.info("dependency_configured service={} dependency={} host={} port={}",
                serviceName(), "redis-cache", settings.host(), settings.port());
    }

    public Optional<String> getDecision(String principal, String resource, String action) {
        String key = decisionKey(principal, resource, action);
        long start = System.nanoTime();
        try (Jedis jedis = pool.getResource()) {
            String value = jedis.get(key);
            log.info("dependency_call service={} dependency={} operation={} outcome={} latency_ms={}",
                    serviceName(), "redis-cache", "get_policy_decision", "success", elapsedMillis(start));
            return Optional.ofNullable(value);
        } catch (RuntimeException ex) {
            log.warn("dependency_call service={} dependency={} operation={} outcome={} latency_ms={} error_type={}",
                    serviceName(), "redis-cache", "get_policy_decision", "failure", elapsedMillis(start), ex.getClass().getSimpleName());
            throw ex;
        }
    }

    public void putDecision(String principal, String resource, String action, String decision) {
        String key = decisionKey(principal, resource, action);
        long start = System.nanoTime();
        try (Jedis jedis = pool.getResource()) {
            jedis.setex(key, DEFAULT_TTL_SECONDS, decision);
            log.info("dependency_call service={} dependency={} operation={} outcome={} latency_ms={}",
                    serviceName(), "redis-cache", "put_policy_decision", "success", elapsedMillis(start));
        } catch (RuntimeException ex) {
            log.warn("dependency_call service={} dependency={} operation={} outcome={} latency_ms={} error_type={}",
                    serviceName(), "redis-cache", "put_policy_decision", "failure", elapsedMillis(start), ex.getClass().getSimpleName());
            throw ex;
        }
    }

    public boolean ping() {
        long start = System.nanoTime();
        try (Jedis jedis = pool.getResource()) {
            String response = jedis.ping();
            boolean ok = "PONG".equalsIgnoreCase(response);
            log.info("dependency_call service={} dependency={} operation={} outcome={} latency_ms={}",
                    serviceName(), "redis-cache", "ping", ok ? "success" : "unexpected_response", elapsedMillis(start));
            return ok;
        } catch (RuntimeException ex) {
            log.warn("dependency_call service={} dependency={} operation={} outcome={} latency_ms={} error_type={}",
                    serviceName(), "redis-cache", "ping", "failure", elapsedMillis(start), ex.getClass().getSimpleName());
            return false;
        }
    }

    public String decisionKey(String principal, String resource, String action) {
        return "policy_decision:" + normalize(principal) + ":" + normalize(resource) + ":" + normalize(action);
    }

    @Override
    public void close() {
        pool.close();
        log.info("dependency_closed service={} dependency={}", serviceName(), "redis-cache");
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim();
    }

    private static long elapsedMillis(long startNanos) {
        return Duration.ofNanos(System.nanoTime() - startNanos).toMillis();
    }

    private static String serviceName() {
        return System.getenv().getOrDefault("APP_NAME", "policy-engine-skill");
    }
}
