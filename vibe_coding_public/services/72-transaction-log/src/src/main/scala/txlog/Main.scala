package txlog

import cats.effect.*
import org.http4s.*
import org.http4s.dsl.io.*
import org.http4s.circe.*
import org.http4s.ember.server.*
import org.http4s.implicits.*
import io.circe.generic.auto.*
import io.circe.syntax.*
import io.circe.Json
import doobie.*
import doobie.implicits.*
import doobie.util.ExecutionContexts
import com.comcast.ip4s.*
import redis.clients.jedis.JedisPool
import redis.clients.jedis.JedisPoolConfig
import org.slf4j.LoggerFactory

case class TxRequest(account_id: Int, amount_cents: Long, tx_type: String, description: String)

object Main extends IOApp:
  val logger = LoggerFactory.getLogger("transaction-log")

  def run(args: List[String]): IO[ExitCode] =
    val pgDsn = sys.env.getOrElse("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
    val streamHost = sys.env.getOrElse("REDIS_STREAM_HOST", "redis-stream")

    val (pgUser, pgPass, pgHost, pgPort, pgDb) = parseDsn(pgDsn)

    val transactor = Transactor.fromDriverManager[IO](
      "org.postgresql.Driver",
      s"jdbc:postgresql://$pgHost:$pgPort/$pgDb",
      pgUser, pgPass, None
    )

    val jedisPool = try
      val cfg = new JedisPoolConfig()
      cfg.setMaxTotal(4)
      new JedisPool(cfg, streamHost, 6379, 2000)
    catch case e: Exception =>
      logger.error("transaction-log: redis init: {}", e.getMessage, e)
      null

    val init = sql"""
      CREATE TABLE IF NOT EXISTS transactions(
        id serial PRIMARY KEY,
        account_id int,
        amount_cents bigint,
        tx_type text,
        description text,
        ts timestamptz DEFAULT now()
      )
    """.update.run.transact(transactor).attempt.flatMap {
      case Left(e) => IO(logger.error("transaction-log: pg init: {}", e.getMessage))
      case Right(_) => IO(logger.info("transaction-log: postgres ready"))
    }

    val routes = HttpRoutes.of[IO] {
      case GET -> Root / "healthz" =>
        Ok(Json.obj("status" -> "ok".asJson, "service" -> "transaction-log".asJson))

      case req @ POST -> Root / "transactions" =>
        for
          body <- req.decodeJson[TxRequest]
          result <- sql"""
            INSERT INTO transactions(account_id,amount_cents,tx_type,description)
            VALUES(${body.account_id},${body.amount_cents},${body.tx_type},${body.description})
            RETURNING id
          """.query[Int].unique.transact(transactor).attempt
          resp <- result match
            case Left(e) =>
              IO(logger.error("transaction-log: {}", e.getMessage, e)) *>
              InternalServerError(Json.obj("error" -> "db error".asJson))
            case Right(id) =>
              IO.delay {
                if jedisPool != null then
                  try
                    val j = jedisPool.getResource()
                    try
                      j.xadd("events:transactions", redis.clients.jedis.StreamEntryID.NEW_ENTRY,
                        java.util.Map.of("account_id", body.account_id.toString,
                          "amount_cents", body.amount_cents.toString, "tx_type", body.tx_type))
                    finally
                      j.close()
                  catch case e: Exception => logger.error("transaction-log: redis: {}", e.getMessage, e)
              } *> Created(Json.obj("id" -> id.asJson))
        yield resp

      case GET -> Root / "transactions" / IntVar(accountId) =>
        sql"""SELECT id,account_id,amount_cents,tx_type,description,ts::text
              FROM transactions WHERE account_id=$accountId ORDER BY ts DESC LIMIT 20"""
          .query[(Int,Int,Long,String,String,String)]
          .to[List]
          .transact(transactor)
          .attempt
          .flatMap {
            case Left(e) =>
              IO(logger.error("transaction-log: {}", e.getMessage, e)) *>
              InternalServerError(Json.obj("error" -> "db error".asJson))
            case Right(rows) =>
              val json = rows.map { case (id,aid,amt,tt,desc,ts) =>
                Json.obj("id"->id.asJson,"account_id"->aid.asJson,"amount_cents"->amt.asJson,
                  "tx_type"->tt.asJson,"description"->desc.asJson,"ts"->ts.asJson)
              }
              Ok(json.asJson)
          }
    }

    EmberServerBuilder.default[IO]
      .withHost(ipv4"0.0.0.0")
      .withPort(port"8080")
      .withHttpApp(routes.orNotFound)
      .build
      .use(_ => init *> IO.never)
      .as(ExitCode.Success)

  def parseDsn(dsn: String): (String,String,String,Int,String) =
    val u = new java.net.URI(dsn)
    val Array(user, pass) = u.getUserInfo.split(":")
    (user, pass, u.getHost, if u.getPort == -1 then 5432 else u.getPort, u.getPath.stripPrefix("/"))
