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
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig
import redis.clients.jedis.StreamEntryID

val logger = LoggerFactory.getLogger("signal-relay")
lateinit var dbConn: Connection
lateinit var streamPool: JedisPool

@Serializable data class SignalIn(val from_user: String, val to_user: String, val signal_type: String, val payload: String)
@Serializable data class SessionIn(val session_id: String, val initiator_user: String, val joiner_user: String)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"
    val streamPort = (System.getenv("REDIS_STREAM_PORT") ?: "6379").toInt()

    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val db = u.path.trimStart('/')
        val jdbcUrl = "jdbc:postgresql://${u.host}:${u.port}/$db?connectTimeout=2&socketTimeout=2&loginTimeout=2"
        dbConn = DriverManager.getConnection(jdbcUrl, user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS signals(
                id bigserial PRIMARY KEY,
                from_user text,
                to_user text,
                signal_type text,
                payload text,
                ts timestamptz DEFAULT now()
            )
        """)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS sessions(
                id bigserial PRIMARY KEY,
                session_id text UNIQUE,
                initiator_user text,
                joiner_user text,
                started_at timestamptz DEFAULT now(),
                ended_at timestamptz
            )
        """)
        logger.info("signal-relay: postgres ready")
    } catch (e: Exception) { logger.error("signal-relay: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        streamPool = JedisPool(cfg, streamHost, streamPort, 2000)
        logger.info("signal-relay: redis-stream ready")
    } catch (e: Exception) { logger.error("signal-relay: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "signal-relay"))
            }

            post("/signals") {
                try {
                    val body = call.receive<SignalIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO signals(from_user,to_user,signal_type,payload) VALUES(?,?,?,?) RETURNING id, ts::text")
                    stmt.setString(1, body.from_user); stmt.setString(2, body.to_user)
                    stmt.setString(3, body.signal_type); stmt.setString(4, body.payload)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        val ts = rs.getString("ts")
                        try {
                            streamPool.resource.use { j ->
                                j.xadd("events:signal:${body.to_user}", StreamEntryID.NEW_ENTRY,
                                    mapOf("from" to body.from_user, "type" to body.signal_type, "payload" to body.payload))
                            }
                        } catch (e: Exception) { logger.error("signal-relay: {}", e.message, e) }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("ok" to true, "id" to id, "ts" to ts))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "insert failed"))
                    }
                } catch (e: Exception) {
                    logger.error("signal-relay: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/signals/{user_id}") {
                val userId = call.parameters["user_id"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT id, from_user, to_user, signal_type, payload, ts::text FROM signals WHERE to_user=? ORDER BY id DESC LIMIT 50")
                    stmt.setString(1, userId)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getLong("id"),
                        "from_user" to rs.getString("from_user"),
                        "to_user" to rs.getString("to_user"),
                        "signal_type" to rs.getString("signal_type"),
                        "payload" to rs.getString("payload"),
                        "ts" to rs.getString("ts")))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("signal-relay: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/sessions") {
                try {
                    val body = call.receive<SessionIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO sessions(session_id,initiator_user,joiner_user) VALUES(?,?,?) ON CONFLICT (session_id) DO NOTHING RETURNING id, started_at::text")
                    stmt.setString(1, body.session_id); stmt.setString(2, body.initiator_user); stmt.setString(3, body.joiner_user)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        val started = rs.getString("started_at")
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf(
                            "id" to id, "session_id" to body.session_id,
                            "initiator_user" to body.initiator_user, "joiner_user" to body.joiner_user,
                            "started_at" to started))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.Conflict, mapOf("error" to "session exists"))
                    }
                } catch (e: Exception) {
                    logger.error("signal-relay: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/sessions/{session_id}/end") {
                val sid = call.parameters["session_id"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "UPDATE sessions SET ended_at=now() WHERE session_id=? RETURNING id, ended_at::text")
                    stmt.setString(1, sid)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        call.respond(mapOf("session_id" to sid, "id" to rs.getLong("id"), "ended_at" to rs.getString("ended_at")))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                    }
                } catch (e: Exception) {
                    logger.error("signal-relay: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/sessions/active") {
                try {
                    val rs = dbConn.createStatement().executeQuery(
                        "SELECT id, session_id, initiator_user, joiner_user, started_at::text FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 100")
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getLong("id"),
                        "session_id" to rs.getString("session_id"),
                        "initiator_user" to rs.getString("initiator_user"),
                        "joiner_user" to rs.getString("joiner_user"),
                        "started_at" to rs.getString("started_at")))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("signal-relay: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
