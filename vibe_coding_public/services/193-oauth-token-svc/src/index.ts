import express, { Request, Response } from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'oauth-token-svc';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const REDIS_CACHE_HOST = process.env.REDIS_CACHE_HOST || 'redis-cache';
const REDIS_CACHE_PORT = process.env.REDIS_CACHE_PORT || '6379';

const app = express();
app.use(express.json());

const pool = new Pool({
  connectionString: PG_DSN,
  connectionTimeoutMillis: 2000,
  statement_timeout: 2000,
  query_timeout: 2000,
  idleTimeoutMillis: 10000,
  max: 4,
});

pool.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: pool error: ${err?.message || err}`);
});

const redis = createClient({
  url: `redis://${REDIS_CACHE_HOST}:${REDIS_CACHE_PORT}`,
  socket: { connectTimeout: 2000 },
});
redis.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: redis error: ${err?.message || err}`);
});

async function withRedisTimeout<T>(p: Promise<T>, ms = 2000): Promise<T> {
  return await Promise.race([
    p,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error('redis timeout')), ms),
    ),
  ]);
}

async function initDb() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS clients(
        id bigserial PRIMARY KEY,
        client_id text UNIQUE,
        client_secret text,
        created_at timestamptz DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS tokens(
        id bigserial PRIMARY KEY,
        token text UNIQUE,
        client_id text,
        expires_at timestamptz,
        issued_at timestamptz DEFAULT now()
      )
    `);
    console.log(`${SERVICE}: db init ok`);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: db init failed: ${e?.message || e}`);
  }
}

app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: SERVICE });
});

app.post('/token', async (req: Request, res: Response) => {
  const { client_id, client_secret, grant_type } = req.body || {};
  if (!client_id || !client_secret || !grant_type) {
    return res.status(400).json({ error: 'client_id, client_secret, grant_type required' });
  }
  try {
    const cr = await pool.query(
      `SELECT id FROM clients WHERE client_id=$1 AND client_secret=$2`,
      [client_id, client_secret],
    );
    if (cr.rowCount === 0) {
      return res.status(401).json({ error: 'invalid_client' });
    }
    const token = Math.random().toString(36).repeat(2);
    const expiresIn = 3600;
    await pool.query(
      `INSERT INTO tokens(token, client_id, expires_at) VALUES($1, $2, now() + interval '3600 seconds')`,
      [token, client_id],
    );
    try {
      await withRedisTimeout(redis.set(`token:${token}`, client_id, { EX: expiresIn }));
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: POST /token cache set: ${e?.message || e}`);
    }
    return res.status(200).json({ access_token: token, expires_in: expiresIn, token_type: 'Bearer' });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /token: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.post('/introspect', async (req: Request, res: Response) => {
  const { token } = req.body || {};
  if (!token) return res.status(400).json({ error: 'token required' });
  try {
    const cached = await withRedisTimeout(redis.get(`token:${token}`));
    if (cached) {
      return res.json({ active: true, client_id: cached });
    }
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /introspect cache get: ${e?.message || e}`);
  }
  try {
    const r = await pool.query(
      `SELECT client_id, expires_at FROM tokens WHERE token=$1 AND expires_at > now()`,
      [token],
    );
    if (r.rowCount === 0) return res.json({ active: false });
    return res.json({
      active: true,
      client_id: r.rows[0].client_id,
      expires_at: r.rows[0].expires_at,
    });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /introspect db: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.post('/revoke', async (req: Request, res: Response) => {
  const { token } = req.body || {};
  if (!token) return res.status(400).json({ error: 'token required' });
  try {
    await pool.query(`DELETE FROM tokens WHERE token=$1`, [token]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /revoke db: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
  try {
    await withRedisTimeout(redis.del(`token:${token}`));
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /revoke cache del: ${e?.message || e}`);
  }
  return res.json({ revoked: true });
});

app.post('/clients', async (req: Request, res: Response) => {
  const { client_id, client_secret } = req.body || {};
  if (!client_id || !client_secret) {
    return res.status(400).json({ error: 'client_id, client_secret required' });
  }
  try {
    const r = await pool.query(
      `INSERT INTO clients(client_id, client_secret) VALUES($1,$2)
       ON CONFLICT (client_id) DO UPDATE SET client_secret=EXCLUDED.client_secret
       RETURNING id, client_id, created_at`,
      [client_id, client_secret],
    );
    return res.status(201).json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /clients: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/tokens/active', async (_req: Request, res: Response) => {
  try {
    const r = await pool.query(`SELECT count(*)::int AS count FROM tokens WHERE expires_at > now()`);
    return res.json({ active: r.rows[0].count });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /tokens/active: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

async function start() {
  await initDb();
  try {
    await redis.connect();
    console.log(`${SERVICE}: redis connected`);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis connect failed: ${e?.message || e}`);
  }
  app.listen(8080, '0.0.0.0', () => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  });
}

start();
