package com.vibe.labresults

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
import redis.clients.jedis.params.XAddParams

val logger = LoggerFactory.getLogger("lab-results")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable
data class LabResultReq(
    val patient_id: String,
    val test_type: String,
    val value: Double,
    val unit: String,
    val reference_range: String
)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"
    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val db = u.path.trimStart('/')
        dbConn = DriverManager.getConnection("jdbc:postgresql://${u.host}:${u.port}/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS lab_results(
                id serial PRIMARY KEY,
                patient_id text,
                test_type text,
                value double precision,
                unit text,
                reference_range text,
                collected_at timestamptz DEFAULT now()
            )
        """)
        logger.info("lab-results: postgres ready")
    } catch (e: Exception) { logger.error("lab-results: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, streamHost, 6379, 2000)
    } catch (e: Exception) { logger.error("lab-results: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") { call.respond(mapOf("status" to "ok", "service" to "lab-results")) }

            post("/results") {
                val body = call.receive<LabResultReq>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO lab_results(patient_id,test_type,value,unit,reference_range) VALUES(?,?,?,?,?) RETURNING id"
                    )
                    stmt.setString(1, body.patient_id)
                    stmt.setString(2, body.test_type)
                    stmt.setDouble(3, body.value)
                    stmt.setString(4, body.unit)
                    stmt.setString(5, body.reference_range)
                    val rs = stmt.executeQuery()
                    val id = if (rs.next()) rs.getInt("id") else 0
                    try {
                        jedisPool.resource.use { j ->
                            j.xadd("events:lab_results", XAddParams.xAddParams(),
                                mapOf("patient_id" to body.patient_id, "test_type" to body.test_type,
                                    "value" to body.value.toString(), "unit" to body.unit))
                        }
                    } catch (e: Exception) { logger.error("lab-results: {}", e.message, e) }
                    call.respond(io.ktor.http.HttpStatusCode.Created,
                        mapOf("id" to id, "patient_id" to body.patient_id, "test_type" to body.test_type))
                } catch (e: Exception) {
                    logger.error("lab-results: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }

            get("/results/{patient_id}") {
                val pid = call.parameters["patient_id"]!!
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT DISTINCT ON (test_type) id,patient_id,test_type,value,unit,reference_range,collected_at::text " +
                        "FROM lab_results WHERE patient_id=? ORDER BY test_type, collected_at DESC LIMIT 10"
                    )
                    stmt.setString(1, pid)
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) {
                        rows.add(mapOf("id" to rs.getInt("id"), "patient_id" to rs.getString("patient_id"),
                            "test_type" to rs.getString("test_type"), "value" to rs.getDouble("value"),
                            "unit" to rs.getString("unit"), "reference_range" to rs.getString("reference_range"),
                            "collected_at" to rs.getString("collected_at")))
                    }
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("lab-results: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
        }
    }.start(wait = true)
}
