import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.application.*
import io.ktor.server.routing.*
import io.ktor.server.response.*
import io.ktor.server.request.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import java.sql.Connection
import java.sql.DriverManager
import java.util.Properties
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("config-store")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class ConfigIn(val key: String, val value: String, val environment: String)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    val cachePort = (System.getenv("REDIS_CACHE_PORT") ?: "6379").toInt()
    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val db = u.path.trimStart('/')
        val props = Properties().apply {
            setProperty("user", user)
            setProperty("password", pass)
            setProperty("loginTimeout", "2")
            setProperty("connectTimeout", "2")
            setProperty("socketTimeout", "2")
        }
        DriverManager.setLoginTimeout(2)
        dbConn = DriverManager.getConnection("jdbc:postgresql://${u.host}:${u.port}/$db", props)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS config_entries(
                id bigserial PRIMARY KEY,
                environment text NOT NULL,
                key text NOT NULL,
                value text,
                updated_at timestamptz DEFAULT now(),
                UNIQUE(environment, key)
            )
        """)
        logger.info("config-store: postgres ready")
    } catch (e: Exception) { logger.error("config-store: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, cacheHost, cachePort, 2000)
        logger.info("config-store: redis-cache ready")
    } catch (e: Exception) { logger.error("config-store: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "config-store"))
            }

            post("/config") {
                try {
                    val body = call.receive<ConfigIn>()
                    val stmt = dbConn.prepareStatement("""
                        INSERT INTO config_entries(environment, key, value, updated_at)
                        VALUES (?, ?, ?, now())
                        ON CONFLICT (environment, key) DO UPDATE
                          SET value = EXCLUDED.value, updated_at = now()
                        RETURNING id, updated_at::text
                    """)
                    stmt.setString(1, body.environment)
                    stmt.setString(2, body.key)
                    stmt.setString(3, body.value)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        val updated = rs.getString("updated_at")
                        try {
                            jedisPool.resource.use { j -> j.setex("cfg:${body.environment}:${body.key}", 600L, body.value) }
                        } catch (e: Exception) { logger.error("config-store: {}", e.message, e) }
                        call.respond(mapOf(
                            "id" to id,
                            "environment" to body.environment,
                            "key" to body.key,
                            "value" to body.value,
                            "updated_at" to updated
                        ))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "upsert failed"))
                    }
                } catch (e: Exception) {
                    logger.error("config-store: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/config/{environment}/{key}") {
                val env = call.parameters["environment"]!!
                val key = call.parameters["key"]!!
                try {
                    val cached: String? = try {
                        jedisPool.resource.use { j -> j.get("cfg:$env:$key") }
                    } catch (e: Exception) { logger.error("config-store: {}", e.message, e); null }
                    if (cached != null) {
                        call.respond(mapOf("environment" to env, "key" to key, "value" to cached, "source" to "cache"))
                        return@get
                    }
                    val stmt = dbConn.prepareStatement(
                        "SELECT value, updated_at::text FROM config_entries WHERE environment=? AND key=?")
                    stmt.setString(1, env); stmt.setString(2, key)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val v = rs.getString("value")
                        val updated = rs.getString("updated_at")
                        try {
                            jedisPool.resource.use { j -> j.setex("cfg:$env:$key", 600L, v ?: "") }
                        } catch (e: Exception) { logger.error("config-store: {}", e.message, e) }
                        call.respond(mapOf(
                            "environment" to env, "key" to key, "value" to v,
                            "updated_at" to updated, "source" to "db"
                        ))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                    }
                } catch (e: Exception) {
                    logger.error("config-store: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/config/{environment}") {
                val env = call.parameters["environment"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT key, value, updated_at::text FROM config_entries WHERE environment=? ORDER BY key ASC")
                    stmt.setString(1, env)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) {
                        rows.add(mapOf(
                            "key" to rs.getString("key"),
                            "value" to rs.getString("value"),
                            "updated_at" to rs.getString("updated_at")
                        ))
                    }
                    call.respond(mapOf("environment" to env, "items" to rows))
                } catch (e: Exception) {
                    logger.error("config-store: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            delete("/config/{environment}/{key}") {
                val env = call.parameters["environment"]!!
                val key = call.parameters["key"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "DELETE FROM config_entries WHERE environment=? AND key=? RETURNING id")
                    stmt.setString(1, env); stmt.setString(2, key)
                    val rs = stmt.executeQuery()
                    val deleted = rs.next()
                    try {
                        jedisPool.resource.use { j -> j.del("cfg:$env:$key") }
                    } catch (e: Exception) { logger.error("config-store: {}", e.message, e) }
                    if (deleted) {
                        call.respond(mapOf("environment" to env, "key" to key, "deleted" to true))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                    }
                } catch (e: Exception) {
                    logger.error("config-store: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/config/{environment}/snapshot") {
                val env = call.parameters["environment"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT key, value FROM config_entries WHERE environment=? ORDER BY key ASC")
                    stmt.setString(1, env)
                    val rs = stmt.executeQuery()
                    val map = linkedMapOf<String, String?>()
                    while (rs.next()) map[rs.getString("key")] = rs.getString("value")
                    call.respond(mapOf("environment" to env, "snapshot" to map, "count" to map.size))
                } catch (e: Exception) {
                    logger.error("config-store: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
