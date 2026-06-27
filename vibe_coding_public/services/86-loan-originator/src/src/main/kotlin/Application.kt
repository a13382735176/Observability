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

val logger = LoggerFactory.getLogger("loan-originator")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class LoanApp(val user_id: String, val amount_cents: Long, val purpose: String)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val (_, db) = u.path.split("/")
        dbConn = DriverManager.getConnection("jdbc:postgresql://${u.host}:${u.port}/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS loans(
                id serial PRIMARY KEY,
                user_id text,
                amount_cents bigint,
                purpose text,
                status text DEFAULT 'pending',
                applied_at timestamptz DEFAULT now()
            )
        """)
        logger.info("loan-originator: postgres ready")
    } catch (e: Exception) { logger.error("loan-originator: {}", e.message, e) }
    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, cacheHost, 6379, 2000)
    } catch (e: Exception) { logger.error("loan-originator: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") { call.respond(mapOf("status" to "ok", "service" to "loan-originator")) }

            post("/loans/apply") {
                val body = call.receive<LoanApp>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO loans(user_id,amount_cents,purpose) VALUES(?,?,?) RETURNING id")
                    stmt.setString(1, body.user_id); stmt.setLong(2, body.amount_cents); stmt.setString(3, body.purpose)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getInt("id")
                        jedisPool.resource.use { j ->
                            j.hset("loan:$id", mapOf("status" to "pending", "user_id" to body.user_id, "amount_cents" to body.amount_cents.toString()))
                            j.expire("loan:$id", 3600L)
                        }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("id" to id, "status" to "pending"))
                    }
                } catch (e: Exception) {
                    logger.error("loan-originator: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/loans/{id}/status") {
                val id = call.parameters["id"]!!.toInt()
                try {
                    val cached = jedisPool.resource.use { j -> j.hgetAll("loan:$id") }
                    if (cached.isNotEmpty()) { call.respond(cached + mapOf("id" to id.toString(), "source" to "cache")); return@get }
                    val stmt = dbConn.prepareStatement("SELECT id,user_id,amount_cents,purpose,status,applied_at::text FROM loans WHERE id=?")
                    stmt.setInt(1, id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) call.respond(mapOf("id" to rs.getInt("id"), "user_id" to rs.getString("user_id"),
                        "amount_cents" to rs.getLong("amount_cents"), "status" to rs.getString("status"),
                        "applied_at" to rs.getString("applied_at")))
                    else call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                } catch (e: Exception) {
                    logger.error("loan-originator: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            put("/loans/{id}/approve") {
                val id = call.parameters["id"]!!.toInt()
                try {
                    val stmt = dbConn.prepareStatement("UPDATE loans SET status='approved' WHERE id=? RETURNING id,status")
                    stmt.setInt(1, id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        jedisPool.resource.use { j -> j.hset("loan:$id", "status", "approved") }
                        call.respond(mapOf("id" to rs.getInt("id"), "status" to rs.getString("status")))
                    } else call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                } catch (e: Exception) {
                    logger.error("loan-originator: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
