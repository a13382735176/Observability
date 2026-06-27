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

val logger = LoggerFactory.getLogger("chat-room")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class RoomIn(val name: String, val owner_id: String)
@Serializable data class MessageIn(val user_id: String, val body: String)
@Serializable data class JoinIn(val user_id: String)

data class PgParts(val user: String, val pass: String, val host: String, val port: Int, val db: String)
fun parseDsn(dsn: String): PgParts {
    val u = java.net.URI(dsn)
    val (user, pass) = u.userInfo.split(":")
    return PgParts(user, pass, u.host, u.port, u.path.trimStart('/'))
}

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"
    val streamPort = (System.getenv("REDIS_STREAM_PORT") ?: "6379").toInt()

    try {
        val p = parseDsn(dsn)
        dbConn = DriverManager.getConnection("jdbc:postgresql://${p.host}:${p.port}/${p.db}", p.user, p.pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS chat_rooms(
                id bigserial PRIMARY KEY,
                name text,
                owner_id text,
                created_at timestamptz DEFAULT now()
            )
        """)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS chat_messages(
                id bigserial PRIMARY KEY,
                room_id bigint,
                user_id text,
                body text,
                created_at timestamptz DEFAULT now()
            )
        """)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS room_members(
                id bigserial PRIMARY KEY,
                room_id bigint,
                user_id text,
                joined_at timestamptz DEFAULT now()
            )
        """)
        logger.info("chat-room: postgres ready")
    } catch (e: Exception) {
        logger.error("chat-room: {}", e.message, e)
    }

    try {
        val cfg = JedisPoolConfig()
        cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, streamHost, streamPort, 2000)
        logger.info("chat-room: redis-stream ready")
    } catch (e: Exception) {
        logger.error("chat-room: {}", e.message, e)
    }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "chat-room"))
            }

            post("/rooms") {
                try {
                    val body = call.receive<RoomIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO chat_rooms(name, owner_id) VALUES(?, ?) RETURNING id, created_at::text"
                    )
                    stmt.setString(1, body.name)
                    stmt.setString(2, body.owner_id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf(
                            "id" to rs.getLong("id"),
                            "name" to body.name,
                            "owner_id" to body.owner_id,
                            "created_at" to rs.getString("created_at")
                        ))
                    }
                } catch (e: Exception) {
                    logger.error("chat-room: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }

            get("/rooms") {
                try {
                    val rs = dbConn.createStatement().executeQuery(
                        "SELECT id, name, owner_id, created_at::text FROM chat_rooms ORDER BY id DESC"
                    )
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getLong("id"),
                        "name" to rs.getString("name"),
                        "owner_id" to rs.getString("owner_id"),
                        "created_at" to rs.getString("created_at")
                    ))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("chat-room: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }

            post("/rooms/{id}/messages") {
                val roomId = call.parameters["id"]!!.toLong()
                try {
                    val body = call.receive<MessageIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO chat_messages(room_id, user_id, body) VALUES(?, ?, ?) RETURNING id, created_at::text"
                    )
                    stmt.setLong(1, roomId)
                    stmt.setString(2, body.user_id)
                    stmt.setString(3, body.body)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        val created = rs.getString("created_at")
                        try {
                            jedisPool.resource.use { j ->
                                j.xadd("events:chat:$roomId", StreamEntryID.NEW_ENTRY,
                                    mapOf("user_id" to body.user_id, "body" to body.body))
                            }
                        } catch (e: Exception) {
                            logger.error("chat-room: {}", e.message, e)
                        }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf(
                            "id" to id,
                            "room_id" to roomId,
                            "user_id" to body.user_id,
                            "body" to body.body,
                            "created_at" to created
                        ))
                    }
                } catch (e: Exception) {
                    logger.error("chat-room: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }

            get("/rooms/{id}/messages") {
                val roomId = call.parameters["id"]!!.toLong()
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT id, room_id, user_id, body, created_at::text FROM chat_messages WHERE room_id=? ORDER BY id DESC LIMIT 50"
                    )
                    stmt.setLong(1, roomId)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getLong("id"),
                        "room_id" to rs.getLong("room_id"),
                        "user_id" to rs.getString("user_id"),
                        "body" to rs.getString("body"),
                        "created_at" to rs.getString("created_at")
                    ))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("chat-room: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }

            post("/rooms/{id}/join") {
                val roomId = call.parameters["id"]!!.toLong()
                try {
                    val body = call.receive<JoinIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO room_members(room_id, user_id) VALUES(?, ?) RETURNING id, joined_at::text"
                    )
                    stmt.setLong(1, roomId)
                    stmt.setString(2, body.user_id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf(
                            "id" to rs.getLong("id"),
                            "room_id" to roomId,
                            "user_id" to body.user_id,
                            "joined_at" to rs.getString("joined_at")
                        ))
                    }
                } catch (e: Exception) {
                    logger.error("chat-room: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
        }
    }.start(wait = true)
}
