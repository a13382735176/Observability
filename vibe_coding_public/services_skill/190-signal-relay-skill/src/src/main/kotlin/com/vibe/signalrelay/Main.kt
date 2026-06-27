package com.vibe.signalrelay

import com.zaxxer.hikari.HikariConfig
import com.zaxxer.hikari.HikariDataSource
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.server.application.Application
import io.ktor.server.application.ApplicationStarted
import io.ktor.server.application.ApplicationStopped
import io.ktor.server.application.call
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.routing
import io.lettuce.core.RedisClient
import io.lettuce.core.RedisURI
import org.slf4j.LoggerFactory
import java.time.Duration
import kotlin.system.exitProcess

private const val SERVICE_ID = "190-signal-relay-skill"
private const val DEFAULT_APP_NAME = "signal-relay-skill"

private val log = LoggerFactory.getLogger("signal-relay-skill")

fun main() {
    val config = RuntimeConfig.fromEnv()
    val dependencies = DependencyManager(config)

    Runtime.getRuntime().addShutdownHook(Thread {
        dependencies.close()
    })

    try {
        val server = embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
            module(config, dependencies)
        }
        server.start(wait = true)
    } catch (t: Throwable) {
        log.error("service_start_failed service={} app={} error_type={} message={}", SERVICE_ID, config.appName, t::class.simpleName, t.message)
        dependencies.close()
        exitProcess(1)
    }
}

fun Application.module(config: RuntimeConfig, dependencies: DependencyManager) {
    environment.monitor.subscribe(ApplicationStarted) {
        log.info("service_started service={} app={} port=8080", SERVICE_ID, config.appName)
        dependencies.initializeSchema()
        dependencies.checkRedis()
    }
    environment.monitor.subscribe(ApplicationStopped) {
        log.info("service_stopped service={} app={}", SERVICE_ID, config.appName)
        dependencies.close()
    }

    routing {
        get("/healthz") {
            val started = System.nanoTime()
            val postgresOk = dependencies.postgresReady()
            val redisOk = dependencies.redisReady()
            val status = HttpStatusCode.OK
            val latencyMs = Duration.ofNanos(System.nanoTime() - started).toMillis()
            log.info(
                "health_checked service={} status={} postgres={} redis={} latency_ms={}",
                SERVICE_ID,
                status.value,
                postgresOk,
                redisOk,
                latencyMs
            )
            val body = "{\"status\":\"ok\",\"service\":\"$SERVICE_ID\",\"postgres\":$postgresOk,\"redis_stream\":$redisOk}"
            call.respondText(body, ContentType.Application.Json, status)
        }
    }
}

data class RuntimeConfig(
    val appName: String,
    val postgresHost: String,
    val postgresPort: Int,
    val postgresDatabase: String,
    val postgresUser: String,
    val postgresPassword: String,
    val redisHost: String,
    val redisPort: Int
) {
    companion object {
        fun fromEnv(): RuntimeConfig = RuntimeConfig(
            appName = env("APP_NAME", DEFAULT_APP_NAME),
            postgresHost = env("POSTGRES_HOST", "postgres"),
            postgresPort = env("POSTGRES_PORT", "5432").toIntOrNull() ?: 5432,
            postgresDatabase = env("POSTGRES_DB", "postgres"),
            postgresUser = env("POSTGRES_USER", "postgres"),
            postgresPassword = env("POSTGRES_PASSWORD", "postgres"),
            redisHost = env("REDIS_STREAM_HOST", "redis-stream"),
            redisPort = env("REDIS_STREAM_PORT", "6379").toIntOrNull() ?: 6379
        )

        private fun env(name: String, defaultValue: String): String =
            System.getenv(name)?.takeIf { it.isNotBlank() } ?: defaultValue
    }
}

class DependencyManager(private val config: RuntimeConfig) : AutoCloseable {
    @Volatile private var dataSource: HikariDataSource? = null
    @Volatile private var redisClient: RedisClient? = null

    fun initializeSchema() {
        val started = System.nanoTime()
        try {
            dataSource().connection.use { connection ->
                connection.createStatement().use { statement ->
                    statement.executeUpdate(
                        "CREATE TABLE IF NOT EXISTS signals(" +
                            " id bigserial PRIMARY KEY," +
                            " from_user text," +
                            " to_user text," +
                            " signal_type text," +
                            " payload text," +
                            " ts timestamptz DEFAULT now()" +
                            " )"
                    )
                    statement.executeUpdate(
                        "CREATE TABLE IF NOT EXISTS sessions(" +
                            " id bigserial PRIMARY KEY," +
                            " session_id text UNIQUE," +
                            " initiator_user text," +
                            " joiner_user text," +
                            " started_at timestamptz DEFAULT now()," +
                            " ended_at timestamptz" +
                            " )"
                    )
                }
            }
            log.info("schema_ready service={} dependency=postgres latency_ms={}", SERVICE_ID, elapsedMs(started))
        } catch (t: Throwable) {
            log.warn("schema_unavailable service={} dependency=postgres error_type={} latency_ms={}", SERVICE_ID, t::class.simpleName, elapsedMs(started))
        }
    }

    fun postgresReady(): Boolean = try {
        dataSource().connection.use { connection ->
            connection.createStatement().use { statement ->
                statement.execute("SELECT 1")
            }
        }
        true
    } catch (t: Throwable) {
        log.warn("dependency_check_failed service={} dependency=postgres error_type={}", SERVICE_ID, t::class.simpleName)
        false
    }

    fun checkRedis() {
        val started = System.nanoTime()
        try {
            redisClient().connect().use { connection ->
                connection.sync().ping()
            }
            log.info("redis_ready service={} dependency=redis-stream latency_ms={}", SERVICE_ID, elapsedMs(started))
        } catch (t: Throwable) {
            log.warn("redis_unavailable service={} dependency=redis-stream error_type={} latency_ms={}", SERVICE_ID, t::class.simpleName, elapsedMs(started))
        }
    }

    fun redisReady(): Boolean = try {
        redisClient().connect().use { connection ->
            connection.sync().ping()
        }
        true
    } catch (t: Throwable) {
        log.warn("dependency_check_failed service={} dependency=redis-stream error_type={}", SERVICE_ID, t::class.simpleName)
        false
    }

    private fun dataSource(): HikariDataSource {
        dataSource?.let { return it }
        synchronized(this) {
            dataSource?.let { return it }
            val hikariConfig = HikariConfig().apply {
                jdbcUrl = "jdbc:postgresql://${config.postgresHost}:${config.postgresPort}/${config.postgresDatabase}"
                username = config.postgresUser
                password = config.postgresPassword
                maximumPoolSize = 3
                minimumIdle = 0
                connectionTimeout = 1500
                validationTimeout = 1000
                initializationFailTimeout = -1
                poolName = "signal-relay-postgres"
            }
            return HikariDataSource(hikariConfig).also { dataSource = it }
        }
    }

    private fun redisClient(): RedisClient {
        redisClient?.let { return it }
        synchronized(this) {
            redisClient?.let { return it }
            val uri = RedisURI.Builder.redis(config.redisHost, config.redisPort)
                .withTimeout(Duration.ofMillis(1500))
                .build()
            return RedisClient.create(uri).also { redisClient = it }
        }
    }

    override fun close() {
        runCatching { dataSource?.close() }
        runCatching { redisClient?.shutdown() }
    }

    private fun elapsedMs(started: Long): Long = Duration.ofNanos(System.nanoTime() - started).toMillis()
}
