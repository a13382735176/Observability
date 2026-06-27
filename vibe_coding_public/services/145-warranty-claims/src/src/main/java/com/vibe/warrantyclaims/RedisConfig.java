package com.vibe.warrantyclaims;

import io.lettuce.core.ClientOptions;
import io.lettuce.core.SocketOptions;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;

@Configuration
public class RedisConfig {

    @Bean(destroyMethod = "destroy")
    public LettuceConnectionFactory streamConnectionFactory() {
        String host = System.getenv().getOrDefault("REDIS_STREAM_HOST", "redis-stream");
        int port = Integer.parseInt(System.getenv().getOrDefault("REDIS_STREAM_PORT", "6379"));
        RedisStandaloneConfiguration cfg = new RedisStandaloneConfiguration(host, port);
        ClientOptions clientOpts = ClientOptions.builder()
                .socketOptions(SocketOptions.builder().connectTimeout(Duration.ofMillis(2000)).build())
                .build();
        LettuceClientConfiguration clientCfg = LettuceClientConfiguration.builder()
                .commandTimeout(Duration.ofMillis(2000))
                .clientOptions(clientOpts)
                .build();
        LettuceConnectionFactory factory = new LettuceConnectionFactory(cfg, clientCfg);
        factory.afterPropertiesSet();
        return factory;
    }

    @Bean
    public StringRedisTemplate redisStreamTemplate(LettuceConnectionFactory streamConnectionFactory) {
        return new StringRedisTemplate(streamConnectionFactory);
    }
}
