import express from 'express';
import { Pool } from 'pg';

const SERVICE = 'subscription-billing';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const app = express();
app.use(express.json());

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.get('/subscriptions/:user_id', async (req, res) => {
  try {
    const { rows } = await pg.query(
      'SELECT * FROM subscriptions WHERE user_id=$1 ORDER BY id', [req.params.user_id]);
    return res.json(rows);
  } catch (e) { log.error('GET /subscriptions failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.post('/subscribe', async (req, res) => {
  const { user_id, plan, price_cents_monthly } = req.body as { user_id: string; plan: string; price_cents_monthly: number };
  try {
    const { rows } = await pg.query(
      'INSERT INTO subscriptions(user_id,plan,price_cents) VALUES($1,$2,$3) RETURNING *',
      [user_id, plan, price_cents_monthly]);
    return res.status(201).json(rows[0]);
  } catch (e) { log.error('POST /subscribe failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.put('/subscriptions/:id/cancel', async (req, res) => {
  try {
    const { rows } = await pg.query(
      "UPDATE subscriptions SET status='cancelled' WHERE id=$1 RETURNING *", [req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'not found' });
    return res.json(rows[0]);
  } catch (e) { log.error('PUT /subscriptions/:id/cancel failed', e); return res.status(500).json({ error: 'internal error' }); }
});

(async () => {
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS subscriptions (
      id SERIAL PRIMARY KEY, user_id TEXT NOT NULL,
      plan TEXT NOT NULL, price_cents INT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TIMESTAMPTZ DEFAULT NOW())`);
    log.info('postgres ready');
  } catch (e) { log.error('postgres init failed', e); }
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
})();
