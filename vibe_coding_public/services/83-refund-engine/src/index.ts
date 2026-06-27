import Fastify from "fastify";
import formbody from "@fastify/formbody";
import { Pool } from "pg";
import { createClient } from "redis";

const app = Fastify({ logger: false });
app.register(formbody);

const PG_DSN = process.env.PG_DSN || "postgres://vibe:vibe@postgres:5432/vibe";
const STREAM_HOST = process.env.REDIS_STREAM_HOST || "redis-stream";

const pg = new Pool({ connectionString: PG_DSN, connectionTimeoutMillis: 2000 });

const redis = createClient({
  socket: { host: STREAM_HOST, port: 6379, connectTimeout: 2000 }
});
redis.on("error", (err: Error) => console.error("ERROR refund-engine:", err));
redis.connect().catch((err: Error) => console.error("ERROR refund-engine: redis connect:", err));

async function initDb() {
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS refunds(
      id serial PRIMARY KEY,
      payment_id int,
      amount_cents bigint,
      reason text,
      status text DEFAULT 'pending',
      created_at timestamptz DEFAULT now()
    )`);
  } catch (err) {
    console.error("ERROR refund-engine:", err);
  }
}

app.get("/healthz", async () => ({ status: "ok", service: "refund-engine" }));

app.post("/refunds", async (req, reply) => {
  const { payment_id, amount_cents, reason } = req.body as any;
  try {
    const res = await pg.query(
      "INSERT INTO refunds(payment_id,amount_cents,reason) VALUES($1,$2,$3) RETURNING id,payment_id,amount_cents,reason,status,created_at",
      [payment_id, amount_cents, reason]
    );
    const row = res.rows[0];
    await redis.xAdd("events:refunds", "*", {
      refund_id: String(row.id),
      payment_id: String(payment_id),
      amount_cents: String(amount_cents),
      reason: reason || ""
    });
    return reply.status(201).send(row);
  } catch (err) {
    console.error("ERROR refund-engine:", err);
    return reply.status(503).send({ error: "error" });
  }
});

app.get("/refunds/:payment_id", async (req, reply) => {
  const { payment_id } = req.params as any;
  try {
    const res = await pg.query(
      "SELECT id,payment_id,amount_cents,reason,status,created_at FROM refunds WHERE payment_id=$1",
      [payment_id]
    );
    return res.rows;
  } catch (err) {
    console.error("ERROR refund-engine:", err);
    return reply.status(503).send({ error: "db error" });
  }
});

app.get("/refund/:id/status", async (req, reply) => {
  const { id } = req.params as any;
  try {
    const res = await pg.query(
      "SELECT id,payment_id,status FROM refunds WHERE id=$1",
      [parseInt(id)]
    );
    if (!res.rows.length) return reply.status(404).send({ error: "not found" });
    return res.rows[0];
  } catch (err) {
    console.error("ERROR refund-engine:", err);
    return reply.status(503).send({ error: "db error" });
  }
});

initDb().then(() => {
  app.listen({ port: 8080, host: "0.0.0.0" }, (err) => {
    if (err) { console.error("ERROR refund-engine:", err); process.exit(1); }
    console.log("refund-engine listening on 8080");
  });
});
