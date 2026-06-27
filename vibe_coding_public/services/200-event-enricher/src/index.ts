import express, { Request, Response } from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'event-enricher';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const REDIS_STREAM_HOST = process.env.REDIS_STREAM_HOST || 'redis-stream';
const REDIS_STREAM_PORT = process.env.REDIS_STREAM_PORT || '6379';
const STREAM_NAME = process.env.STREAM_NAME || 'events:enriched';

const app = express();
app.use(express.json({ limit: '1mb' }));

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
  url: `redis://${REDIS_STREAM_HOST}:${REDIS_STREAM_PORT}`,
  socket: { connectTimeout: 2000 },
});
redis.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: redis error: ${err?.message || err}`);
});

async function withTimeout<T>(p: Promise<T>, ms = 2000): Promise<T> {
  return await Promise.race([
    p,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error('timeout')), ms)),
  ]);
}

async function initDb() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS enrich_events(
        id BIGSERIAL PRIMARY KEY,
        tenant TEXT NOT NULL,
        event_type TEXT NOT NULL,
        payload JSONB NOT NULL,
        enriched JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE INDEX IF NOT EXISTS enrich_events_tenant_idx
      ON enrich_events(tenant, id DESC)
    `);
    await pool.query(`
      CREATE INDEX IF NOT EXISTS enrich_events_type_idx
      ON enrich_events(event_type, id DESC)
    `);
    console.log(`${SERVICE}: db init ok`);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: db init failed: ${e?.message || e}`);
  }
}

function normalizePayload(payload: any): Record<string, any> {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return {};
  }
  return payload as Record<string, any>;
}

function enrichEvent(tenant: string, eventType: string, payload: Record<string, any>) {
  return {
    ...payload,
    _meta: {
      tenant,
      event_type: eventType,
      enriched_at: new Date().toISOString(),
      source: SERVICE,
    },
  };
}

app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: SERVICE });
});

app.post('/enrich', async (req: Request, res: Response) => {
  const { tenant, event_type, payload } = req.body || {};
  if (!tenant || !event_type) {
    return res.status(400).json({ error: 'tenant and event_type required' });
  }

  const raw = normalizePayload(payload);
  const enriched = enrichEvent(String(tenant), String(event_type), raw);

  try {
    const result = await pool.query(
      `INSERT INTO enrich_events(tenant, event_type, payload, enriched)
       VALUES($1, $2, $3::jsonb, $4::jsonb)
       RETURNING id, tenant, event_type, enriched, created_at`,
      [tenant, event_type, JSON.stringify(raw), JSON.stringify(enriched)],
    );

    const row = result.rows[0];
    try {
      await withTimeout(redis.xAdd(STREAM_NAME, '*', {
        id: String(row.id),
        tenant: String(row.tenant),
        event_type: String(row.event_type),
        created_at: String(row.created_at),
      }));
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: POST /enrich stream: ${e?.message || e}`);
    }

    return res.status(201).json({
      id: row.id,
      tenant: row.tenant,
      event_type: row.event_type,
      enriched: row.enriched,
      created_at: row.created_at,
    });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /enrich db: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/enrich/:id', async (req: Request, res: Response) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id) || id <= 0) {
    return res.status(400).json({ error: 'invalid id' });
  }
  try {
    const r = await pool.query(
      `SELECT id, tenant, event_type, payload, enriched, created_at
       FROM enrich_events WHERE id=$1`,
      [id],
    );
    if (r.rowCount === 0) {
      return res.status(404).json({ error: 'not found' });
    }
    return res.json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /enrich/${id} db: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/recent', async (req: Request, res: Response) => {
  const limitRaw = Number(req.query.limit || 20);
  const limit = Number.isInteger(limitRaw) ? Math.min(Math.max(limitRaw, 1), 200) : 20;
  try {
    const r = await pool.query(
      `SELECT id, tenant, event_type, enriched, created_at
       FROM enrich_events ORDER BY id DESC LIMIT $1`,
      [limit],
    );
    return res.json({ items: r.rows });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /recent db: ${e?.message || e}`);
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
