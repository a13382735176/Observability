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
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.slf4j.LoggerFactory
import java.sql.Connection
import java.sql.DriverManager
import redis.clients.jedis.Jedis
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("funnel-analyzer")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class FunnelIn(val name: String, val steps: List<String>)
@Serializable data class TrackIn(val user_id: String, val event_type: String)

fun pgHost(): String = System.getenv("PGHOST") ?: System.getenv("POSTGRES_HOST") ?: "postgres"
fun pgPort(): String = System.getenv("PGPORT") ?: System.getenv("POSTGRES_PORT") ?: "5432"

fun stepsToJsonArray(steps: List<String>): String =
    "[" + steps.joinToString(",") { "\"" + it.replace("\\", "\\\\").replace("\"", "\\\"") + "\"" } + "]"

fun parseStepsJson(raw: String?): List<String> {
    if (raw.isNullOrBlank()) return emptyList()
    return try {
        Json.parseToJsonElement(raw).jsonArray.map { it.jsonPrimitive.content }
    } catch (e: Exception) {
        logger.error("funnel-analyzer: {}", e.message, e)
        emptyList()
    }
}

fun main() {
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    val cachePort = (System.getenv("REDIS_CACHE_PORT") ?: "6379").toInt()
    try {
        val url = "jdbc:postgresql://${pgHost()}:${pgPort()}/vibe?user=vibe&password=vibe&connectTimeout=2&socketTimeout=2&loginTimeout=2"
        dbConn = DriverManager.getConnection(url)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS funnels(
                id bigserial PRIMARY KEY,
                name text,
                steps jsonb,
                created_at timestamptz DEFAULT now()
            )
        """)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS funnel_events(
                id bigserial PRIMARY KEY,
                funnel_id bigint,
                user_id text,
                event_type text,
                ts timestamptz DEFAULT now()
            )
        """)
        logger.info("funnel-analyzer: postgres ready")
    } catch (e: Exception) { logger.error("funnel-analyzer: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig()
        cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, cacheHost, cachePort, 2000)
        logger.info("funnel-analyzer: redis-cache ready")
    } catch (e: Exception) { logger.error("funnel-analyzer: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                try {
                    call.respond(mapOf("status" to "ok", "service" to "funnel-analyzer"))
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                }
            }

            post("/funnels") {
                try {
                    val body = call.receive<FunnelIn>()
                    val stepsJson = stepsToJsonArray(body.steps)
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO funnels(name, steps) VALUES(?, ?::jsonb) RETURNING id")
                    stmt.setString(1, body.name)
                    stmt.setString(2, stepsJson)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        call.respond(io.ktor.http.HttpStatusCode.Created,
                            mapOf("id" to id, "name" to body.name, "steps" to body.steps))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "no id"))
                    }
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/funnels/{id}/track") {
                try {
                    val id = call.parameters["id"]!!.toLong()
                    val body = call.receive<TrackIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO funnel_events(funnel_id, user_id, event_type) VALUES(?, ?, ?) RETURNING id, ts::text")
                    stmt.setLong(1, id)
                    stmt.setString(2, body.user_id)
                    stmt.setString(3, body.event_type)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val eid = rs.getLong("id")
                        val ts = rs.getString("ts")
                        try { jedisPool.resource.use { j -> j.del("funnel:$id:conversion") } } catch (e: Exception) { logger.error("funnel-analyzer: {}", e.message, e) }
                        call.respond(io.ktor.http.HttpStatusCode.Created,
                            mapOf("id" to eid, "funnel_id" to id, "user_id" to body.user_id, "event_type" to body.event_type, "ts" to ts))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "no id"))
                    }
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/funnels/{id}/conversion") {
                try {
                    val id = call.parameters["id"]!!.toLong()
                    val cacheKey = "funnel:$id:conversion"
                    val cached: String? = try { jedisPool.resource.use { j -> j.get(cacheKey) } } catch (e: Exception) { logger.error("funnel-analyzer: {}", e.message, e); null }
                    if (cached != null) {
                        call.respondText(cached, io.ktor.http.ContentType.Application.Json)
                        return@get
                    }

                    val fstmt = dbConn.prepareStatement("SELECT steps::text FROM funnels WHERE id=?")
                    fstmt.setLong(1, id)
                    val frs = fstmt.executeQuery()
                    if (!frs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                        return@get
                    }
                    val steps = parseStepsJson(frs.getString(1))
                    if (steps.isEmpty()) {
                        call.respondText("[]", io.ktor.http.ContentType.Application.Json)
                        return@get
                    }

                    // user_id -> first ts per event_type
                    val perStep: MutableList<MutableMap<String, java.sql.Timestamp>> = MutableList(steps.size) { mutableMapOf() }
                    for ((idx, step) in steps.withIndex()) {
                        val estmt = dbConn.prepareStatement(
                            "SELECT user_id, MIN(ts) AS first_ts FROM funnel_events WHERE funnel_id=? AND event_type=? GROUP BY user_id")
                        estmt.setLong(1, id)
                        estmt.setString(2, step)
                        val ers = estmt.executeQuery()
                        while (ers.next()) {
                            perStep[idx][ers.getString("user_id")] = ers.getTimestamp("first_ts")
                        }
                    }

                    val firstStepCount = perStep[0].size
                    val result = StringBuilder("[")
                    // step 0
                    val firstConv = if (firstStepCount == 0) 0.0 else 1.0
                    result.append("""{"step":"${steps[0].replace("\"", "\\\"")}","count":$firstStepCount,"conv":$firstConv}""")

                    // carry: user_id -> ts at previous step (must be strictly increasing)
                    var carry: MutableMap<String, java.sql.Timestamp> = perStep[0].toMutableMap()
                    for (i in 1 until steps.size) {
                        val next = mutableMapOf<String, java.sql.Timestamp>()
                        for ((uid, prevTs) in carry) {
                            val ts = perStep[i][uid]
                            if (ts != null && ts.after(prevTs)) next[uid] = ts
                        }
                        val cnt = next.size
                        val conv = if (firstStepCount == 0) 0.0 else cnt.toDouble() / firstStepCount.toDouble()
                        result.append(""",{"step":"${steps[i].replace("\"", "\\\"")}","count":$cnt,"conv":$conv}""")
                        carry = next
                    }
                    result.append("]")
                    val payload = result.toString()
                    try { jedisPool.resource.use { j -> j.setex(cacheKey, 60L, payload) } } catch (e: Exception) { logger.error("funnel-analyzer: {}", e.message, e) }
                    call.respondText(payload, io.ktor.http.ContentType.Application.Json)
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/funnels") {
                try {
                    val rs = dbConn.createStatement().executeQuery(
                        "SELECT id, name, steps::text, created_at::text FROM funnels ORDER BY id DESC")
                    val out = StringBuilder("[")
                    var first = true
                    while (rs.next()) {
                        if (!first) out.append(",")
                        first = false
                        val sid = rs.getLong("id")
                        val nm = rs.getString("name").replace("\"", "\\\"")
                        val st = rs.getString(3) ?: "[]"
                        val ca = rs.getString(4)
                        out.append("""{"id":$sid,"name":"$nm","steps":$st,"created_at":"$ca"}""")
                    }
                    out.append("]")
                    call.respondText(out.toString(), io.ktor.http.ContentType.Application.Json)
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/funnels/{id}/users-completed") {
                try {
                    val id = call.parameters["id"]!!.toLong()
                    val fstmt = dbConn.prepareStatement("SELECT steps::text FROM funnels WHERE id=?")
                    fstmt.setLong(1, id)
                    val frs = fstmt.executeQuery()
                    if (!frs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                        return@get
                    }
                    val steps = parseStepsJson(frs.getString(1))
                    if (steps.isEmpty()) {
                        call.respondText("""{"funnel_id":$id,"users":[]}""", io.ktor.http.ContentType.Application.Json)
                        return@get
                    }
                    val finalStep = steps.last()
                    val ustmt = dbConn.prepareStatement(
                        "SELECT DISTINCT user_id FROM funnel_events WHERE funnel_id=? AND event_type=? ORDER BY user_id")
                    ustmt.setLong(1, id)
                    ustmt.setString(2, finalStep)
                    val urs = ustmt.executeQuery()
                    val users = mutableListOf<String>()
                    while (urs.next()) users.add(urs.getString(1))
                    val payload = """{"funnel_id":$id,"final_step":"${finalStep.replace("\"", "\\\"")}","users":[${users.joinToString(",") { "\"${it.replace("\"", "\\\"")}\"" }}]}"""
                    call.respondText(payload, io.ktor.http.ContentType.Application.Json)
                } catch (e: Exception) {
                    logger.error("funnel-analyzer: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
