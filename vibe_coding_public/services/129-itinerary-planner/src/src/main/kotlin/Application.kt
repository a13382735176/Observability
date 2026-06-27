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
import redis.clients.jedis.Jedis
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("itinerary-planner")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class ItineraryIn(val user_id: String, val title: String, val start_date: String, val end_date: String)
@Serializable data class ItemIn(val day: Int, val activity: String, val location: String? = null)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    val cachePort = (System.getenv("REDIS_CACHE_PORT") ?: "6379").toInt()
    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val db = u.path.trimStart('/')
        dbConn = DriverManager.getConnection("jdbc:postgresql://${u.host}:${u.port}/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS itineraries(
                id serial PRIMARY KEY,
                user_id text,
                title text,
                start_date date,
                end_date date,
                created_at timestamptz DEFAULT now()
            )
        """)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS itinerary_items(
                id serial PRIMARY KEY,
                itinerary_id int REFERENCES itineraries(id) ON DELETE CASCADE,
                day int,
                activity text,
                location text
            )
        """)
        logger.info("itinerary-planner: postgres ready")
    } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, cacheHost, cachePort, 2000)
        logger.info("itinerary-planner: redis-cache ready")
    } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "itinerary-planner"))
            }

            post("/itineraries") {
                try {
                    val body = call.receive<ItineraryIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO itineraries(user_id,title,start_date,end_date) VALUES(?,?,?::date,?::date) RETURNING id, created_at::text")
                    stmt.setString(1, body.user_id); stmt.setString(2, body.title)
                    stmt.setString(3, body.start_date); stmt.setString(4, body.end_date)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getInt("id")
                        val created = rs.getString("created_at")
                        val payload = """{"id":$id,"user_id":"${body.user_id}","title":"${body.title}","start_date":"${body.start_date}","end_date":"${body.end_date}","created_at":"$created","items":[]}"""
                        try { jedisPool.resource.use { j -> j.setex("itin:$id", 600L, payload) } } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e) }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("id" to id, "user_id" to body.user_id, "title" to body.title, "start_date" to body.start_date, "end_date" to body.end_date, "created_at" to created))
                    }
                } catch (e: Exception) {
                    logger.error("itinerary-planner: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/itineraries/{id}") {
                val id = call.parameters["id"]!!.toInt()
                try {
                    val cached: String? = try { jedisPool.resource.use { j -> j.get("itin:$id") } } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e); null }
                    if (cached != null) {
                        call.respondText(cached, io.ktor.http.ContentType.Application.Json)
                        return@get
                    }
                    val stmt = dbConn.prepareStatement("SELECT id,user_id,title,start_date::text,end_date::text,created_at::text FROM itineraries WHERE id=?")
                    stmt.setInt(1, id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val title = rs.getString("title")
                        val userId = rs.getString("user_id")
                        val sd = rs.getString("start_date"); val ed = rs.getString("end_date"); val ca = rs.getString("created_at")
                        val items = mutableListOf<Map<String, Any?>>()
                        val istmt = dbConn.prepareStatement("SELECT id,day,activity,location FROM itinerary_items WHERE itinerary_id=? ORDER BY day,id")
                        istmt.setInt(1, id)
                        val irs = istmt.executeQuery()
                        while (irs.next()) items.add(mapOf("id" to irs.getInt("id"), "day" to irs.getInt("day"), "activity" to irs.getString("activity"), "location" to irs.getString("location")))
                        val itemsJson = items.joinToString(",") { """{"id":${it["id"]},"day":${it["day"]},"activity":"${it["activity"]}","location":${(it["location"] as String?)?.let { l -> "\"$l\"" } ?: "null"}}""" }
                        val payload = """{"id":$id,"user_id":"$userId","title":"$title","start_date":"$sd","end_date":"$ed","created_at":"$ca","items":[$itemsJson]}"""
                        try { jedisPool.resource.use { j -> j.setex("itin:$id", 600L, payload) } } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e) }
                        call.respondText(payload, io.ktor.http.ContentType.Application.Json)
                    } else call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                } catch (e: Exception) {
                    logger.error("itinerary-planner: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/itineraries/{id}/items") {
                val id = call.parameters["id"]!!.toInt()
                try {
                    val body = call.receive<ItemIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO itinerary_items(itinerary_id,day,activity,location) VALUES(?,?,?,?) RETURNING id")
                    stmt.setInt(1, id); stmt.setInt(2, body.day); stmt.setString(3, body.activity); stmt.setString(4, body.location)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val newId = rs.getInt("id")
                        try { jedisPool.resource.use { j -> j.del("itin:$id") } } catch (e: Exception) { logger.error("itinerary-planner: {}", e.message, e) }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("id" to newId, "itinerary_id" to id, "day" to body.day, "activity" to body.activity, "location" to body.location))
                    }
                } catch (e: Exception) {
                    logger.error("itinerary-planner: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/users/{user_id}/itineraries") {
                val userId = call.parameters["user_id"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT id,title,start_date::text,end_date::text,created_at::text FROM itineraries WHERE user_id=? ORDER BY id DESC")
                    stmt.setString(1, userId)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getInt("id"),
                        "title" to rs.getString("title"),
                        "start_date" to rs.getString("start_date"),
                        "end_date" to rs.getString("end_date"),
                        "created_at" to rs.getString("created_at")))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("itinerary-planner: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
