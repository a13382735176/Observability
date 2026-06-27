import express, { Request, Response } from 'express';
import { Pool } from 'pg';
import { createClient, RedisClientType } from 'redis';

const SERVICE = 'order-history';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const REDIS_HOST = process.env.REDIS_CACHE_HOST || 'redis-cache';
const REDIS_PORT = parseInt(process.env.REDIS_CACHE_PORT || '6379', 10);

const app = express();
app.use(express.json());

const pool = new Pool({
  connectionString: PG_DSN,
  connectionTimeoutMillis: 2000,
  statement_timeout: 2000,
  query_timeout: 2000,
  idleTimeoutMillis: 10000,
  max: 8,
});
pool.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: pool error: ${err?.message || err}`);
});

const redis: RedisClientType = createClient({
  socket: {
    host: REDIS_HOST,
    port: REDIS_PORT,
    connectTimeout: 2000,
  },
});
redis.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: redis error: ${err?.message || err}`);
});

async function initDb() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS order_history(
        id bigserial PRIMARY KEY,
        user_id text,
        total_cents bigint,
        item_count int,
        created_at timestamptz DEFAULT now()
      )
    `);
    console.log(`${SERVICE}: db init ok`);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: db init failed: ${e?.message || e}`);
  }
}

function orderKey(id: number | string) { return `order:${id}`; }
function userZKey(userId: string) { return `user_orders:${userId}`; }

function rowToJson(row: any) {
  return {
    id: Number(row.id),
    user_id: row.user_id,
    total_cents: Number(row.total_cents),
    item_count: Number(row.item_count),
    created_at: row.created_at instanceof Date ? row.created_at.toISOString() : row.created_at,
  };
}

app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: SERVICE });
});

app.post('/orders', async (req: Request, res: Response) => {
  const { user_id, total_cents, item_count } = req.body || {};
  if (!user_id || typeof total_cents !== 'number' || typeof item_count !== 'number') {
    return res.status(400).json({ error: 'user_id, total_cents, item_count required' });
  }
  let row: any;
  try {
    const r = await pool.query(
      `INSERT INTO order_history(user_id, total_cents, item_count)
       VALUES($1,$2,$3)
       RETURNING id, user_id, total_cents, item_count, created_at`,
      [user_id, total_cents, item_count],
    );
    row = r.rows[0];
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /orders: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
  const json = rowToJson(row);
  const createdMs = new Date(json.created_at).getTime();
  try {
    await redis.zAdd(userZKey(user_id), { score: createdMs, value: String(json.id) });
    await redis.set(orderKey(json.id), JSON.stringify(json), { EX: 3600 });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis write: ${e?.message || e}`);
  }
  return res.status(201).json(json);
});

app.get('/orders/:id', async (req: Request, res: Response) => {
  const id = req.params.id;
  if (!/^[0-9]+$/.test(id)) return res.status(400).json({ error: 'invalid id' });
  try {
    const cached = await redis.get(orderKey(id));
    if (cached) return res.json(JSON.parse(cached));
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis get: ${e?.message || e}`);
  }
  try {
    const r = await pool.query(
      `SELECT id, user_id, total_cents, item_count, created_at
       FROM order_history WHERE id=$1`,
      [id],
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    const json = rowToJson(r.rows[0]);
    try {
      await redis.set(orderKey(id), JSON.stringify(json), { EX: 3600 });
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: redis setex: ${e?.message || e}`);
    }
    return res.json(json);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /orders/:id: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

async function listForUser(userId: string, n: number, res: Response) {
  let ids: string[] = [];
  let hadRedis = false;
  try {
    ids = await redis.zRange(userZKey(userId), 0, n - 1, { REV: true });
    hadRedis = true;
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis zrange: ${e?.message || e}`);
  }

  if (hadRedis && ids.length > 0) {
    let cached: (string | null)[] = [];
    try {
      cached = await redis.mGet(ids.map(orderKey));
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: redis mget: ${e?.message || e}`);
    }
    const anyMissing = cached.length !== ids.length || cached.some((v) => v == null);
    if (!anyMissing) {
      return res.json(cached.map((v) => JSON.parse(v as string)));
    }
  }

  try {
    const r = await pool.query(
      `SELECT id, user_id, total_cents, item_count, created_at
       FROM order_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2`,
      [userId, n],
    );
    const rows = r.rows.map(rowToJson);
    try {
      const multi = redis.multi();
      for (const row of rows) {
        multi.zAdd(userZKey(userId), { score: new Date(row.created_at).getTime(), value: String(row.id) });
        multi.set(orderKey(row.id), JSON.stringify(row), { EX: 3600 });
      }
      await multi.exec();
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: redis warm: ${e?.message || e}`);
    }
    return res.json(rows);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: list user orders: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
}

app.get('/orders/user/:user_id', async (req: Request, res: Response) => {
  return listForUser(req.params.user_id, 20, res);
});

app.get('/orders/user/:user_id/recent', async (req: Request, res: Response) => {
  let n = parseInt(String(req.query.n || '10'), 10);
  if (!Number.isFinite(n) || n <= 0) n = 10;
  if (n > 100) n = 100;
  return listForUser(req.params.user_id, n, res);
});

app.delete('/orders/:id', async (req: Request, res: Response) => {
  const id = req.params.id;
  if (!/^[0-9]+$/.test(id)) return res.status(400).json({ error: 'invalid id' });
  let userId: string | null = null;
  try {
    const r = await pool.query(
      `DELETE FROM order_history WHERE id=$1 RETURNING user_id`,
      [id],
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    userId = r.rows[0].user_id;
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: DELETE /orders/:id: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
  try {
    await redis.del(orderKey(id));
    if (userId) await redis.zRem(userZKey(userId), id);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis cleanup: ${e?.message || e}`);
  }
  return res.json({ id: Number(id), deleted: true });
});

(async () => {
  try {
    await redis.connect();
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis connect: ${e?.message || e}`);
  }
  await initDb();
  app.listen(8080, '0.0.0.0', () => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  });
})();
