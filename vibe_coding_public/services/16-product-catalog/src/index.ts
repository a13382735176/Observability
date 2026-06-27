import express from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'product-catalog';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const redis = createClient({
  socket: { host: process.env.REDIS_CACHE_HOST || 'redis-cache',
            port: parseInt(process.env.REDIS_CACHE_PORT || '6379'),
            connectTimeout: 2000 },
});
redis.on('error', (e) => log.error('redis error', e));

const app = express();
app.use(express.json());

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.get('/products', async (_req, res) => {
  try {
    const cached = await redis.get('products:all');
    if (cached) return res.json(JSON.parse(cached));
    const { rows } = await pg.query('SELECT * FROM products ORDER BY id');
    await redis.setEx('products:all', 30, JSON.stringify(rows));
    return res.json(rows);
  } catch (e) { log.error('GET /products failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/products/:id', async (req, res) => {
  try {
    const key = `product:${req.params.id}`;
    const cached = await redis.get(key);
    if (cached) return res.json(JSON.parse(cached));
    const { rows } = await pg.query('SELECT * FROM products WHERE id=$1', [req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'not found' });
    await redis.setEx(key, 60, JSON.stringify(rows[0]));
    return res.json(rows[0]);
  } catch (e) { log.error('GET /products/:id failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.post('/products', async (req, res) => {
  const { sku, name, description, price_cents } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO products(sku,name,description,price_cents) VALUES($1,$2,$3,$4) RETURNING *',
      [sku, name, description || '', price_cents]);
    await redis.del('products:all');
    return res.status(201).json(rows[0]);
  } catch (e) { log.error('POST /products failed', e); return res.status(500).json({ error: 'internal error' }); }
});

(async () => {
  await redis.connect();
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS products (
      id SERIAL PRIMARY KEY, sku TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL, description TEXT DEFAULT '',
      price_cents INT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())`);
    log.info('postgres ready');
  } catch (e) { log.error('postgres init failed', e); }
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
})();
