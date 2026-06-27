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

val logger = LoggerFactory.getLogger("device-group")
lateinit var dbConn: Connection

@Serializable data class CreateGroup(val name: String, val device_ids: List<String>)
@Serializable data class AddDevice(val device_id: String)

fun main() {
    val dsn = System.getenv("PG_DSN") ?: "postgres://vibe:vibe@postgres:5432/vibe"
    try {
        val (user, pass, host, port, db) = parseDsn(dsn)
        dbConn = DriverManager.getConnection("jdbc:postgresql://$host:$port/$db", user, pass)
        dbConn.createStatement().execute("""
            CREATE TABLE IF NOT EXISTS groups(id serial PRIMARY KEY, name text UNIQUE);
            CREATE TABLE IF NOT EXISTS group_devices(group_id int, device_id text, PRIMARY KEY(group_id, device_id));
        """)
        logger.info("device-group: postgres ready")
    } catch (e: Exception) {
        logger.error("device-group: {}", e.message, e)
    }

    embeddedServer(Netty, port = 8080, host = "0.0.0.0") {
        install(ContentNegotiation) { json(Json { ignoreUnknownKeys = true }) }
        routing {
            get("/healthz") {
                call.respond(mapOf("status" to "ok", "service" to "device-group"))
            }
            post("/groups") {
                val body = call.receive<CreateGroup>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO groups(name) VALUES(?) ON CONFLICT(name) DO NOTHING RETURNING id"
                    )
                    stmt.setString(1, body.name)
                    val rs = stmt.executeQuery()
                    if (!rs.next()) {
                        call.respond(io.ktor.http.HttpStatusCode.Conflict, mapOf("error" to "name exists"))
                        return@post
                    }
                    val groupId = rs.getInt("id")
                    for (did in body.device_ids) {
                        val ins = dbConn.prepareStatement(
                            "INSERT INTO group_devices(group_id,device_id) VALUES(?,?) ON CONFLICT DO NOTHING"
                        )
                        ins.setInt(1, groupId)
                        ins.setString(2, did)
                        ins.executeUpdate()
                    }
                    call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("id" to groupId, "name" to body.name))
                } catch (e: Exception) {
                    logger.error("device-group: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
            get("/groups") {
                try {
                    val rs = dbConn.createStatement().executeQuery("SELECT id,name FROM groups ORDER BY id")
                    val rows = mutableListOf<Map<String, Any>>()
                    while (rs.next()) rows.add(mapOf("id" to rs.getInt("id"), "name" to rs.getString("name")))
                    call.respond(rows)
                } catch (e: Exception) {
                    logger.error("device-group: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
            get("/groups/{id}/devices") {
                val gid = call.parameters["id"]!!.toInt()
                try {
                    val stmt = dbConn.prepareStatement("SELECT device_id FROM group_devices WHERE group_id=?")
                    stmt.setInt(1, gid)
                    val rs = stmt.executeQuery()
                    val devices = mutableListOf<String>()
                    while (rs.next()) devices.add(rs.getString("device_id"))
                    call.respond(mapOf("group_id" to gid, "devices" to devices))
                } catch (e: Exception) {
                    logger.error("device-group: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
                }
            }
            post("/groups/{id}/add") {
                val gid = call.parameters["id"]!!.toInt()
                val body = call.receive<AddDevice>()
                try {
                    val stmt = dbConn.prepareStatement(
                        "INSERT INTO group_devices(group_id,device_id) VALUES(?,?) ON CONFLICT DO NOTHING"
                    )
                    stmt.setInt(1, gid)
                    stmt.setString(2, body.device_id)
                    stmt.executeUpdate()
                    call.respond(io.ktor.http.HttpStatusCode.Created, mapOf("ok" to true))
                } catch (e: Exception) {
                    logger.error("device-group: {}", e.message, e)
                    call.respond(io.ktor.http.HttpStatusCode.ServiceUnavailable, mapOf("error" to "db error"))
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
