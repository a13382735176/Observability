import express from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'checkout-service';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const stream = createClient({
  socket: { host: process.env.REDIS_STREAM_HOST || 'redis-stream',
            port: parseInt(process.env.REDIS_STREAM_PORT || '6379'),
            connectTimeout: 2000 },
});
stream.on('error', (e) => log.error('redis-stream error', e));

const app = express();
app.use(express.json());

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.post('/checkout', async (req, res) => {
  const { user_id, items } = req.body as { user_id: string; items: { sku: string; qty: number }[] };
  const total = (items || []).reduce((s, i) => s + i.qty * 100, 0);
  try {
    const { rows } = await pg.query(
      'INSERT INTO orders(user_id,total_cents,status) VALUES($1,$2,$3) RETURNING *',
      [user_id, total, 'pending']);
    const order = rows[0];
    try {
      await stream.xAdd('orders:queue', '*', {
        event: 'order.created', order_id: String(order.id), user_id, total_cents: String(total)
      });
    } catch (e) { log.error('stream publish failed', e); }
    return res.status(201).json(order);
  } catch (e) { log.error('POST /checkout failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/orders/:user_id', async (req, res) => {
  try {
    const { rows } = await pg.query(
      'SELECT * FROM orders WHERE user_id=$1 ORDER BY id DESC', [req.params.user_id]);
    return res.json(rows);
  } catch (e) { log.error('GET /orders failed', e); return res.status(500).json({ error: 'internal error' }); }
});

(async () => {
  await stream.connect();
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS orders (
      id SERIAL PRIMARY KEY, user_id TEXT NOT NULL,
      total_cents INT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      created_at TIMESTAMPTZ DEFAULT NOW())`);
    log.info('postgres ready');
  } catch (e) { log.error('postgres init failed', e); }
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
})();
