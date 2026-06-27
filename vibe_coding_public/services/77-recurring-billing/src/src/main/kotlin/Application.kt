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
import java.time.OffsetDateTime
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("recurring-billing")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class Schedule(val user_id: String, val amount_cents: Int, val interval_days: Int)
@Serializable data class TriggerResp(val ok: Boolean)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"

    try {
        val (user, pass, host, port, db) = parseDsn(dsn)
        dbConn = DriverManager.getConnection("jdbc:postgresql://$host:$port/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS billing_schedules(
                id serial PRIMARY KEY,
                user_id text,
                amount_cents int,
                interval_days int,
                next_run timestamptz DEFAULT now(),
                active bool DEFAULT true
            )
        """)
        logger.info("recurring-billing: postgres ready")
    } catch (e: Exception) {
        logger.error("recurring-billing: {}", e.message, e)
    }

    try {
        val cfg = JedisPoolConfig()
        cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, streamHost, 6379, 2000)
    } catch (e: Exception) {
        logger.error("recurring-billing: {}", e.message, e)
    }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "recurring-billing"))
            }
            post("/schedules") {
                val body = call.receive<Schedule>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO billing_schedules(user_id,amount_cents,interval_days) VALUES(?,?,?) RETURNING id"
                    )
                    stmt.setString(1, body.user_id)
                    stmt.setInt(2, body.amount_cents)
                    stmt.setInt(3, body.interval_days)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.Created,
                            mapOf("id" to rs.getInt("id"), "user_id" to body.user_id))
                    }
                } catch (e: Exception) {
                    logger.error("recurring-billing: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
            get("/schedules/{user_id}") {
                val uid = call.parameters["user_id"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT id,user_id,amount_cents,interval_days,next_run::text,active FROM billing_schedules WHERE user_id=?"
                    )
                    stmt.setString(1, uid)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) {
                        rows.add(mapOf("id" to rs.getInt("id"), "user_id" to rs.getString("user_id"),
                            "amount_cents" to rs.getInt("amount_cents"), "interval_days" to rs.getInt("interval_days"),
                            "next_run" to rs.getString("next_run"), "active" to rs.getBoolean("active")))
                    }
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("recurring-billing: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
            post("/trigger/{schedule_id}") {
                val sid = call.parameters["schedule_id"]!!.toInt()
                try {
                    jedisPool.resource.use { j ->
                        j.xadd("events:billing", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                            mapOf("schedule_id" to sid.toString()))
                    }
                    call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("ok" to true))
                } catch (e: Exception) {
                    logger.error("recurring-billing: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "stream error"))
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
