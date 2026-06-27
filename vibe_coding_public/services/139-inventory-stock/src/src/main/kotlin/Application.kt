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
import java.util.Properties
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig

val logger = LoggerFactory.getLogger("inventory-stock")
lateinit var dbConn: Connection
lateinit var jedisPool: JedisPool

@Serializable data class ItemIn(val sku: String, val name: String, val quantity: Int, val warehouse_id: String)
@Serializable data class AdjustIn(val delta: Int)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    val cacheHost = System.getenv("REDIS_CACHE_HOST") ?: "redis-cache"
    val cachePort = (System.getenv("REDIS_CACHE_PORT") ?: "6379").toInt()
    try {
        val u = java.net.URI(dsn)
        val (user, pass) = u.userInfo.split(":")
        val db = u.path.trimStart('/')
        val props = Properties().apply {
            setProperty("user", user)
            setProperty("password", pass)
            setProperty("connectTimeout", "2")
            setProperty("socketTimeout", "2")
        }
        dbConn = DriverManager.getConnection("jdbc:postgresql://${u.host}:${u.port}/$db", props)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS inventory_items(
                id bigserial PRIMARY KEY,
                sku text UNIQUE,
                name text,
                quantity int DEFAULT 0,
                warehouse_id text,
                updated_at timestamptz DEFAULT now()
            )
        """)
        logger.info("inventory-stock: postgres ready")
    } catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e) }

    try {
        val cfg = JedisPoolConfig(); cfg.maxTotal = 4
        jedisPool = JedisPool(cfg, cacheHost, cachePort, 2000)
        logger.info("inventory-stock: redis-cache ready")
    } catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e) }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "inventory-stock"))
            }

            post("/items") {
                try {
                    val body = call.receive<ItemIn>()
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO inventory_items(sku,name,quantity,warehouse_id) VALUES(?,?,?,?) " +
                        "ON CONFLICT (sku) DO UPDATE SET name=EXCLUDED.name, quantity=EXCLUDED.quantity, warehouse_id=EXCLUDED.warehouse_id, updated_at=now() " +
                        "RETURNING id, sku, name, quantity, warehouse_id, updated_at::text"
                    )
                    stmt.setString(1, body.sku); stmt.setString(2, body.name)
                    stmt.setInt(3, body.quantity); stmt.setString(4, body.warehouse_id)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val id = rs.getLong("id")
                        val updatedAt = rs.getString("updated_at")
                        try { jedisPool.resource.use { j -> j.setex("stock:${body.sku}", 600L, body.quantity.toString()) } }
                        catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e) }
                        call.respond(io.ktor.http.HttpStatusCode.Created, mapOf(
                            "id" to id, "sku" to body.sku, "name" to body.name,
                            "quantity" to body.quantity, "warehouse_id" to body.warehouse_id,
                            "updated_at" to updatedAt
                        ))
                    }
                } catch (e: Exception) {
                    logger.error("inventory-stock: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/items/low-stock") {
                try {
                    val stmt = dbConn.prepareStatement(
                        "SELECT id, sku, name, quantity, warehouse_id, updated_at::text FROM inventory_items WHERE quantity < 10 ORDER BY quantity ASC LIMIT 200"
                    )
                    val rs = stmt.executeQuery()
                    val rows = mutableListOf<Map<String, Any?>>()
                    while (rs.next()) rows.add(mapOf(
                        "id" to rs.getLong("id"),
                        "sku" to rs.getString("sku"),
                        "name" to rs.getString("name"),
                        "quantity" to rs.getInt("quantity"),
                        "warehouse_id" to rs.getString("warehouse_id"),
                        "updated_at" to rs.getString("updated_at")
                    ))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("inventory-stock: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            post("/items/{sku}/adjust") {
                val sku = call.parameters["sku"]!!
                try {
                    val body = call.receive<AdjustIn>()
                    val stmt = dbConn.prepareStatement(
                        "UPDATE inventory_items SET quantity = quantity + ?, updated_at = now() WHERE sku=? " +
                        "RETURNING id, sku, name, quantity, warehouse_id, updated_at::text"
                    )
                    stmt.setInt(1, body.delta); stmt.setString(2, sku)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        try { jedisPool.resource.use { j -> j.del("stock:$sku") } }
                        catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e) }
                        call.respond(mapOf(
                            "id" to rs.getLong("id"),
                            "sku" to rs.getString("sku"),
                            "name" to rs.getString("name"),
                            "quantity" to rs.getInt("quantity"),
                            "warehouse_id" to rs.getString("warehouse_id"),
                            "updated_at" to rs.getString("updated_at")
                        ))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                    }
                } catch (e: Exception) {
                    logger.error("inventory-stock: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }

            get("/items/{sku}") {
                val sku = call.parameters["sku"]!!
                try {
                    val cached: String? = try { jedisPool.resource.use { j -> j.get("stock:$sku") } }
                        catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e); null }
                    if (cached != null) {
                        call.respond(mapOf("sku" to sku, "quantity" to cached.toInt(), "source" to "cache"))
                        return@get
                    }
                    val stmt = dbConn.prepareStatement(
                        "SELECT id, sku, name, quantity, warehouse_id, updated_at::text FROM inventory_items WHERE sku=?"
                    )
                    stmt.setString(1, sku)
                    val rs = stmt.executeQuery()
                    if (rs.next()) {
                        val qty = rs.getInt("quantity")
                        try { jedisPool.resource.use { j -> j.setex("stock:$sku", 600L, qty.toString()) } }
                        catch (e: Exception) { logger.error("inventory-stock: {}", e.message, e) }
                        call.respond(mapOf(
                            "id" to rs.getLong("id"),
                            "sku" to rs.getString("sku"),
                            "name" to rs.getString("name"),
                            "quantity" to qty,
                            "warehouse_id" to rs.getString("warehouse_id"),
                            "updated_at" to rs.getString("updated_at"),
                            "source" to "db"
                        ))
                    } else {
                        call.respond(io.ktor.http.HttpStatusCode.NotFound, mapOf("error" to "not found"))
                    }
                } catch (e: Exception) {
                    logger.error("inventory-stock: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "error"))
                }
            }
        }
    }.start(wait = true)
}
