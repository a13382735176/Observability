package com.vibe.statuspage;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.jedis.JedisClientConfiguration;
import org.springframework.data.redis.connection.jedis.JedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;

@Configuration
public class RedisConfig {

    @Value("${redis.cache.host:redis-cache}")
    private String host;

    @Value("${redis.cache.port:6379}")
    private int port;

    @Bean
    public JedisConnectionFactory redisConnectionFactory() {
        RedisStandaloneConfiguration cfg = new RedisStandaloneConfiguration(host, port);
        JedisClientConfiguration client = JedisClientConfiguration.builder()
                .connectTimeout(Duration.ofMillis(2000))
                .readTimeout(Duration.ofMillis(2000))
                .build();
        return new JedisConnectionFactory(cfg, client);
    }

    @Bean
    public StringRedisTemplate stringRedisTemplate(JedisConnectionFactory cf) {
        return new StringRedisTemplate(cf);
    }
}
