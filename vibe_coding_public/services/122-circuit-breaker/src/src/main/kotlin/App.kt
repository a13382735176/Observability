package com.vibe.cb

import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import io.ktor.server.application.*
import io.ktor.server.engine.*
import io.ktor.server.netty.*
import io.ktor.server.plugins.contentnegotiation.*
import io.ktor.server.request.*
import io.ktor.server.response.*
import io.ktor.server.routing.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.slf4j.LoggerFactory
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

private val logger = LoggerFactory.getLogger("circuit-breaker")

private fun envOr(k: String, d: String) = System.getenv(k)?.takeIf { it.isNotBlank() } ?: d

@Serializable data class HealthResp(val status: String, val service: String)
@Serializable data class RecordReq(val service_name: String, val success: Boolean)
@Serializable data class StateResp(val service: String, val state: String, val success: Long, val fail: Long, val fail_rate: Double)
@Serializable data class ErrorResp(val error: String)

object RedisHolder {
    val pool: JedisPool
    init {
        val cfg = JedisPoolConfig().apply {
            maxTotal = 16
            maxIdle = 8
            minIdle = 1
        }
        val host = envOr("REDIS_CACHE_HOST", "redis-cache")
        val port = envOr("REDIS_CACHE_PORT", "6379").toInt()
        pool = JedisPool(cfg, host, port, 2000)
    }
}

fun main() {
    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) {
            json(Json { ignoreUnknownKeys = true })
        }
        routing {
            get("/healthz") {
                call.respond(HealthResp("ok", "circuit-breaker"))
            }
            post("/record") {
                val req = try { call.receive<RecordReq>() } catch (e: Exception) {
                    logger.error("circuit-breaker: bad body: {}", e.message, e)
                    call.respond(HttpStatusCode.BadRequest, ErrorResp("invalid body"))
                    return@post
                }
                val field = if (req.success) "success" else "fail"
                try {
                    RedisHolder.pool.resource.use { jedis ->
                        jedis.hincrBy("cb:${req.service_name}", field, 1)
                    }
                    call.respond(HttpStatusCode.Accepted, mapOf("recorded" to true))
                } catch (e: Exception) {
                    logger.error("circuit-breaker: hincrby: {}", e.message, e)
                    call.respond(HttpStatusCode.BadGateway, ErrorResp("cache error"))
                }
            }
            get("/state/{service_name}") {
                val name = call.parameters["service_name"] ?: run {
                    call.respond(HttpStatusCode.BadRequest, ErrorResp("service_name required"))
                    return@get
                }
                try {
                    val m = RedisHolder.pool.resource.use { it.hgetAll("cb:$name") }
                    val success = m["success"]?.toLongOrNull() ?: 0
                    val fail = m["fail"]?.toLongOrNull() ?: 0
                    val total = success + fail
                    val rate = if (total > 0) fail.toDouble() / total else 0.0
                    val state = if (total >= 10 && rate > 0.5) "open" else "closed"
                    call.respond(StateResp(name, state, success, fail, rate))
                } catch (e: Exception) {
                    logger.error("circuit-breaker: hgetall: {}", e.message, e)
                    call.respond(HttpStatusCode.BadGateway, ErrorResp("cache error"))
                }
            }
            post("/reset/{service_name}") {
                val name = call.parameters["service_name"] ?: run {
                    call.respond(HttpStatusCode.BadRequest, ErrorResp("service_name required"))
                    return@post
                }
                try {
                    RedisHolder.pool.resource.use { it.del("cb:$name") }
                    call.respond(HttpStatusCode.NoContent)
                } catch (e: Exception) {
                    logger.error("circuit-breaker: del: {}", e.message, e)
                    call.respond(HttpStatusCode.BadGateway, ErrorResp("cache error"))
                }
            }
        }
    }.start(wait = true)
}
