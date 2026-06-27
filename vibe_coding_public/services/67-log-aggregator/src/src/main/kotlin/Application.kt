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
import java.sql.DriverManager
import java.sql.Connection
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("log-aggregator")

lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable
data class LogEntry(val device_id: String, val level: String, val message: String)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"

    try {
        val (user, pass, host, port, db) = parseDsn(dsn)
        dbConn = DriverManager.getConnection("jdbc:postgresql://$host:$port/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS device_logs(
                id serial PRIMARY KEY,
                device_id text,
                level text,
                message text,
                ts timestamptz DEFAULT now()
            )
        """)
        logger.info("log-aggregator: postgres ready")
    } catch (e: Exception) {
        logger.error("log-aggregator: {}", e.message, e)
    }

    try {
        val cfg = JedisPoolConfig()
        cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, streamHost, 6379, 2000)
        logger.info("log-aggregator: redis ready")
    } catch (e: Exception) {
        logger.error("log-aggregator: {}", e.message, e)
    }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "log-aggregator"))
            }
            post("/logs") {
                val entry = call.receive<LogEntry>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO device_logs(device_id,level,message) VALUES(?,?,?)"
                    )
                    stmt.setString(1, entry.device_id)
                    stmt.setString(2, entry.level)
                    stmt.setString(3, entry.message)
                    stmt.executeUpdate()
                } catch (e: Exception) {
                    logger.error("log-aggregator: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                    return@post
                }
                try {
                    jedisPool.resource.use { j ->
                        j.xadd("events:logs", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                            mapOf("device_id" to entry.device_id, "level" to entry.level, "message" to entry.message))
                    }
                } catch (e: Exception) {
                    logger.error("log-aggregator: {}", e.message, e)
                }
                call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("ok" to true))
            }
            get("/logs/{device_id}") {
                val devId = call.parameters["device_id"]!!
                try {
                    val rs = dbConn.prepareStatement(
                        "SELECT id,device_id,level,message,ts FROM device_logs WHERE device_id=? ORDER BY ts DESC LIMIT 50"
                    ).also { it.setString(1, devId) }.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) {
                        rows.add(mapOf("id" to rs.getInt("id"), "device_id" to rs.getString("device_id"),
                            "level" to rs.getString("level"), "message" to rs.getString("message"),
                            "ts" to rs.getTimestamp("ts").toString()))
                    }
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("log-aggregator: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
        }
    }.start(wait = true)
}

data class PgParts(val user: String, val pass: String, val host: String, val port: Int, val db: String)
fun parseDsn(dsn: String): PgParts {
    val u = java.net.URI(dsn)
    val (user, pass) = u.userInfo.split(":")
    return PgParts(user, pass, u.host, if (u.port == -1) 5432 else u.port, u.path.trimStart('/'))
}

operator fun PgParts.component1() = user
operator fun PgParts.component2() = pass
operator fun PgParts.component3() = host
operator fun PgParts.component4() = port
operator fun PgParts.component5() = db
