package com.vibe

import io.ktor.server.application.*
import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.serialization.json.*
import org.slf4j.LoggerFactory
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig
import java.sql.DriverManager

val logger = LoggerFactory.getLogger("share-service")

fun main() {
    val pgDsn = System.getenv("PG_DSN") ?: "jdbc:postgresql://postgres:5432/vibe"
    val jdbcUrl = if (pgDsn.startsWith("postgres://")) {
        val u = pgDsn.removePrefix("postgres://")
        val creds = u.substringBefore("@")
        val hostDb = u.substringAfter("@")
        "jdbc:postgresql://$hostDb?user=${creds.substringBefore(":")}& password=${creds.substringAfter(":")}"
    } else pgDsn

    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"
    val streamPort = System.getenv("REDIS_STREAM_PORT")?.toIntOrNull() ?: 6379
    val jedisPool = JedisPool(JedisPoolConfig().apply { maxTotal = 5 }, streamHost, streamPort, 2000)

    // init DB
    try {
        DriverManager.getConnection("jdbc:postgresql://postgres:5432/vibe", "vibe", "vibe").use { conn ->
            conn.createStatement().execute(
                "CREATE TABLE IF NOT EXISTS shares(id SERIAL PRIMARY KEY, user_id TEXT NOT NULL," +
                "content_id TEXT NOT NULL, platform TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())")
        }
        logger.info("share-service: db init ok")
    } catch (e: Exception) {
        logger.error("share-service: db init failed: {}", e.message, e)
    }

    embeddedServer(Netty, port = 8080) {
        install(ContentNegotiation) { json() }
        routing {
            get("/healthz") { call.respond(mapOf("status" to "ok", "service" to "share-service")) }

            post("/share") {
                val body = call.receiveText()
                val json = Json.parseToJsonElement(body).jsonObject
                val userId = json["user_id"]?.jsonPrimitive?.content ?: return@post call.respond(io.ktor.http.HttpStatusCode.BadRequest, mapOf("error" to "missing user_id"))
                val contentId = json["content_id"]?.jsonPrimitive?.content ?: return@post call.respond(io.ktor.http.HttpStatusCode.BadRequest, mapOf("error" to "missing content_id"))
                val platform = json["platform"]?.jsonPrimitive?.content ?: "unknown"
                try {
                    var shareId = 0
                    DriverManager.getConnection("jdbc:postgresql://postgres:5432/vibe", "vibe", "vibe").use { conn ->
                        val ps = conn.prepareStatement("INSERT INTO shares(user_id,content_id,platform) VALUES(?,?,?) RETURNING id")
                        ps.setString(1, userId); ps.setString(2, contentId); ps.setString(3, platform)
                        val rs = ps.executeQuery(); rs.next(); shareId = rs.getInt(1)
                    }
                    jedisPool.resource.use { jedis ->
                        jedis.xadd("events:shares", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                            mapOf("event" to "share.created", "user_id" to userId, "content_id" to contentId, "platform" to platform))
                    }
                    call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("id" to shareId, "user_id" to userId, "content_id" to contentId, "platform" to platform))
                } catch (e: Exception) {
                    logger.error("share-service: POST /share: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.InternalServerError, mapOf("error" to "internal error"))
                }
            }

            get("/shares/{content_id}") {
                val contentId = call.parameters["content_id"] ?: ""
                try {
                    val rows = mutableListOf<Map<String, Any>>()
                    DriverManager.getConnection("jdbc:postgresql://postgres:5432/vibe", "vibe", "vibe").use { conn ->
                        val ps = conn.prepareStatement("SELECT id,user_id,content_id,platform,created_at FROM shares WHERE content_id=? ORDER BY id")
                        ps.setString(1, contentId)
                        val rs = ps.executeQuery()
                        while (rs.next()) rows.add(mapOf("id" to rs.getInt(1), "user_id" to rs.getString(2), "content_id" to rs.getString(3), "platform" to rs.getString(4), "created_at" to rs.getString(5)))
                    }
                    call.respond(mapOf("content_id" to contentId, "shares" to rows))
                } catch (e: Exception) {
                    logger.error("share-service: GET /shares/{}: {}", contentId, e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.InternalServerError, mapOf("error" to "internal error"))
                }
            }
        }
    }.start(wait = true)
}
