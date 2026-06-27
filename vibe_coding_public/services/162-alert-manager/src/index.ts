import express, { Request, Response } from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'alert-manager';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const REDIS_STREAM_HOST = process.env.REDIS_STREAM_HOST || 'redis-stream';
const REDIS_STREAM_PORT = process.env.REDIS_STREAM_PORT || '6379';

const log = (msg: string) => console.log(`${new Date().toISOString()} ${SERVICE} :: ${msg}`);
const logErr = (where: string, e: unknown) =>
  console.error(`ERROR ${SERVICE}: ${where}: ${(e as any)?.message || e}`);

const pool = new Pool({
  connectionString: PG_DSN,
  connectionTimeoutMillis: 2000,
  statement_timeout: 2000,
  query_timeout: 2000,
  idleTimeoutMillis: 10000,
  max: 4,
});
pool.on('error', (e: Error) => logErr('pg-pool', e));

const stream = createClient({
  url: `redis://${REDIS_STREAM_HOST}:${REDIS_STREAM_PORT}`,
  socket: { connectTimeout: 2000 },
});
stream.on('error', (e: Error) => logErr('redis-stream', e));

async function initDb() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS alert_rules(
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        metric TEXT NOT NULL,
        threshold DOUBLE PRECISION NOT NULL,
        comparator TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
      )`);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS alerts(
        id BIGSERIAL PRIMARY KEY,
        rule_id BIGINT,
        metric TEXT NOT NULL,
        value DOUBLE PRECISION NOT NULL,
        acknowledged BOOLEAN DEFAULT false,
        ack_at TIMESTAMPTZ,
        fired_at TIMESTAMPTZ DEFAULT now()
      )`);
    log('db init ok');
  } catch (e) {
    logErr('initDb', e);
  }
}

(async () => {
  try {
    await stream.connect();
    log('redis-stream connected');
  } catch (e) {
    logErr('redis-stream connect', e);
  }
})();

const app = express();
app.use(express.json());

app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: SERVICE });
});

app.post('/rules', async (req: Request, res: Response) => {
  const { name, metric, threshold, comparator } = req.body || {};
  if (!name || !metric || typeof threshold !== 'number' || !comparator) {
    return res.status(400).json({ error: 'name, metric, threshold, comparator required' });
  }
  if (!['gt', 'lt', 'eq'].includes(comparator)) {
    return res.status(400).json({ error: 'comparator must be gt|lt|eq' });
  }
  try {
    const r = await pool.query(
      `INSERT INTO alert_rules(name,metric,threshold,comparator)
       VALUES($1,$2,$3,$4) RETURNING id,name,metric,threshold,comparator,created_at`,
      [name, metric, threshold, comparator],
    );
    res.status(201).json(r.rows[0]);
  } catch (e) {
    logErr('POST /rules', e);
    res.status(503).json({ error: 'db error' });
  }
});

app.get('/rules', async (_req: Request, res: Response) => {
  try {
    const r = await pool.query(
      `SELECT id,name,metric,threshold,comparator,created_at FROM alert_rules ORDER BY id DESC`,
    );
    res.json(r.rows);
  } catch (e) {
    logErr('GET /rules', e);
    res.status(503).json({ error: 'db error' });
  }
});

app.post('/evaluate', async (req: Request, res: Response) => {
  const { metric, value } = req.body || {};
  if (!metric || typeof value !== 'number') {
    return res.status(400).json({ error: 'metric and numeric value required' });
  }
  try {
    const rules = await pool.query(
      `SELECT id,name,metric,threshold,comparator FROM alert_rules WHERE metric=$1`,
      [metric],
    );
    const fired: any[] = [];
    for (const rule of rules.rows) {
      const t = Number(rule.threshold);
      let trigger = false;
      if (rule.comparator === 'gt') trigger = value > t;
      else if (rule.comparator === 'lt') trigger = value < t;
      else if (rule.comparator === 'eq') trigger = value === t;
      if (!trigger) continue;
      try {
        const ins = await pool.query(
          `INSERT INTO alerts(rule_id,metric,value) VALUES($1,$2,$3)
           RETURNING id,rule_id,metric,value,acknowledged,fired_at`,
          [rule.id, metric, value],
        );
        const alert = ins.rows[0];
        fired.push(alert);
        try {
          await stream.xAdd('events:alerts', '*', {
            id: String(alert.id),
            name: rule.name,
            value: String(value),
          });
        } catch (xe) {
          logErr('xAdd events:alerts', xe);
        }
      } catch (ie) {
        logErr('insert alert', ie);
      }
    }
    res.json({ evaluated: rules.rows.length, fired });
  } catch (e) {
    logErr('POST /evaluate', e);
    res.status(503).json({ error: 'db error' });
  }
});

app.get('/alerts', async (_req: Request, res: Response) => {
  try {
    const r = await pool.query(
      `SELECT id,rule_id,metric,value,acknowledged,ack_at,fired_at
         FROM alerts ORDER BY fired_at DESC LIMIT 100`,
    );
    res.json(r.rows);
  } catch (e) {
    logErr('GET /alerts', e);
    res.status(503).json({ error: 'db error' });
  }
});

app.put('/alerts/:id/ack', async (req: Request, res: Response) => {
  const id = req.params.id;
  try {
    const r = await pool.query(
      `UPDATE alerts SET acknowledged=true, ack_at=now() WHERE id=$1
       RETURNING id,rule_id,metric,value,acknowledged,ack_at,fired_at`,
      [id],
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    res.json(r.rows[0]);
  } catch (e) {
    logErr(`PUT /alerts/${id}/ack`, e);
    res.status(503).json({ error: 'db error' });
  }
});

initDb().finally(() => {
  app.listen(8080, '0.0.0.0', () => log('listening on :8080'));
});
