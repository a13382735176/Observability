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

val logger = LoggerFactory.getLogger("live-viewer")

fun main() {
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    val cachePort = System.getenv("REDIS_CACHE_PORT")?.toIntOrNull() ?: 6379
    val streamHost = System.getenv("REDIS_STREAM_HOST") ?: "redis-stream"
    val streamPort = System.getenv("REDIS_STREAM_PORT")?.toIntOrNull() ?: 6379

    val cfg = JedisPoolConfig().apply { maxTotal = 5 }
    val cachePool = JedisPool(cfg, cacheHost, cachePort, 2000)
    val streamPool = JedisPool(JedisPoolConfig().apply { maxTotal = 5 }, streamHost, streamPort, 2000)

    embeddedServer(Netty, port = 8080) {
        install(ContentNegotiation) { json() }
        routing {
            get("/healthz") { call.respond(mapOf("status" to "ok", "service" to "live-viewer")) }

            post("/join") {
                val body = call.receiveText()
                val json = Json.parseToJsonElement(body).jsonObject
                val streamId = json["stream_id"]?.jsonPrimitive?.content ?: return@post call.respond(io.ktor.http.HttpStatusCode.BadRequest, mapOf("error" to "missing stream_id"))
                val userId = json["user_id"]?.jsonPrimitive?.content ?: return@post call.respond(io.ktor.http.HttpStatusCode.BadRequest, mapOf("error" to "missing user_id"))
                try {
                    val count = cachePool.resource.use { jedis ->
                        jedis.sadd("live:$streamId:viewers", userId)
                        jedis.scard("live:$streamId:viewers")
                    }
                    streamPool.resource.use { jedis ->
                        jedis.xadd("events:live", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                            mapOf("event" to "viewer.join", "stream_id" to streamId, "user_id" to userId))
                    }
                    call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("stream_id" to streamId, "user_id" to userId, "viewer_count" to count))
                } catch (e: Exception) {
                    logger.error("live-viewer: POST /join: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.InternalServerError, mapOf("error" to "internal error"))
                }
            }

            post("/leave") {
                val body = call.receiveText()
                val json = Json.parseToJsonElement(body).jsonObject
                val streamId = json["stream_id"]?.jsonPrimitive?.content ?: ""
                val userId = json["user_id"]?.jsonPrimitive?.content ?: ""
                try {
                    val count = cachePool.resource.use { jedis ->
                        jedis.srem("live:$streamId:viewers", userId)
                        jedis.scard("live:$streamId:viewers")
                    }
                    call.respond(mapOf("stream_id" to streamId, "user_id" to userId, "viewer_count" to count))
                } catch (e: Exception) {
                    logger.error("live-viewer: POST /leave: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.InternalServerError, mapOf("error" to "internal error"))
                }
            }

            get("/viewers/{stream_id}") {
                val streamId = call.parameters["stream_id"] ?: ""
                try {
                    val (count, viewers) = cachePool.resource.use { jedis ->
                        Pair(jedis.scard("live:$streamId:viewers"), jedis.smembers("live:$streamId:viewers"))
                    }
                    call.respond(mapOf("stream_id" to streamId, "viewer_count" to count, "viewers" to viewers))
                } catch (e: Exception) {
                    logger.error("live-viewer: GET /viewers/{}: {}", streamId, e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.InternalServerError, mapOf("error" to "internal error"))
                }
            }
        }
    }.start(wait = true)
}
