import Fastify from "fastify";
import { Pool } from "pg";
import { createClient } from "redis";

const PG_DSN = process.env.PG_DSN || "postgres://vibe:vibe@postgres:5432/vibe";
const REDIS_HOST = process.env.REDIS_CACHE_HOST || "redis-cache";

function parsePort(raw: string | undefined, fallback = 6379): number {
  const v = (raw || "").trim();
  if (!v) return fallback;
  if (/^\d+$/.test(v)) return Number(v);
  const m = v.match(/:(\d+)(?:\/|$)/);
  if (m) return Number(m[1]);
  return fallback;
}

const REDIS_PORT = parsePort(process.env.REDIS_CACHE_PORT, 6379);

const pool = new Pool({ connectionString: PG_DSN, connectionTimeoutMillis: 2000, max: 5 });
const rdb = createClient({
  socket: { host: REDIS_HOST, port: REDIS_PORT, connectTimeout: 2000 },
});
rdb.on("error", (e: Error) => console.error("ERROR secret-rotation: redis client:", e.message));

const app = Fastify({ logger: false });

async function init() {
  try {
    await pool.query(`CREATE TABLE IF NOT EXISTS secrets_audit (
      id SERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      version INT NOT NULL,
      rotated_at TIMESTAMPTZ DEFAULT NOW(),
      rotated_by TEXT DEFAULT 'system'
    )`);
    console.log("secret-rotation: postgres ready");
  } catch (e: any) {
    console.error("ERROR secret-rotation: postgres init:", e?.message ?? e);
  }
  try {
    await rdb.connect();
    console.log("secret-rotation: redis ready");
  } catch (e: any) {
    console.error("ERROR secret-rotation: redis init:", e?.message ?? e);
  }
}

app.get("/healthz", async () => ({ status: "ok", service: "secret-rotation" }));

app.post("/secrets", async (req, reply) => {
  const body = req.body as { name?: string; value?: string };
  if (!body?.name || !body?.value) return reply.code(400).send({ error: "name and value required" });
  try {
    const r = await pool.query(
      "INSERT INTO secrets_audit(name, version) VALUES($1, 1) RETURNING id, version, rotated_at",
      [body.name],
    );
    const row = r.rows[0];
    try {
      await rdb.hSet(`secret:${body.name}`, { value: body.value, version: String(row.version), rotated_at: String(row.rotated_at) });
      await rdb.expire(`secret:${body.name}`, 86400);
    } catch (e: any) {
      console.error("ERROR secret-rotation: redis HSET:", e?.message ?? e);
    }
    return reply.code(201).send({ name: body.name, version: row.version });
  } catch (e: any) {
    console.error("ERROR secret-rotation: POST /secrets:", e?.message ?? e);
    return reply.code(502).send({ error: "postgres error" });
  }
});

app.get("/secrets/:name/metadata", async (req, reply) => {
  const name = (req.params as { name: string }).name;
  try {
    const r = await pool.query(
      "SELECT version, rotated_at FROM secrets_audit WHERE name=$1 ORDER BY version DESC LIMIT 1",
      [name],
    );
    if (r.rowCount === 0) return reply.code(404).send({ error: "not found" });
    return { name, version: r.rows[0].version, rotated_at: r.rows[0].rotated_at };
  } catch (e: any) {
    console.error("ERROR secret-rotation: GET metadata:", e?.message ?? e);
    return reply.code(502).send({ error: "postgres error" });
  }
});

app.post("/secrets/:name/rotate", async (req, reply) => {
  const name = (req.params as { name: string }).name;
  const body = req.body as { new_value?: string };
  if (!body?.new_value) return reply.code(400).send({ error: "new_value required" });
  try {
    const r = await pool.query(
      `INSERT INTO secrets_audit(name, version)
       VALUES($1, COALESCE((SELECT MAX(version) FROM secrets_audit WHERE name=$1), 0) + 1)
       RETURNING version, rotated_at`,
      [name],
    );
    const row = r.rows[0];
    try {
      await rdb.hSet(`secret:${name}`, { value: body.new_value, version: String(row.version), rotated_at: String(row.rotated_at) });
      await rdb.expire(`secret:${name}`, 86400);
    } catch (e: any) {
      console.error("ERROR secret-rotation: redis HSET on rotate:", e?.message ?? e);
    }
    return { name, version: row.version, rotated_at: row.rotated_at };
  } catch (e: any) {
    console.error("ERROR secret-rotation: rotate:", e?.message ?? e);
    return reply.code(502).send({ error: "postgres error" });
  }
});

init().finally(() => {
  app.listen({ host: "0.0.0.0", port: 8080 }).catch((e: Error) => {
    console.error("ERROR secret-rotation: listen:", e.message);
    process.exit(1);
  });
});
