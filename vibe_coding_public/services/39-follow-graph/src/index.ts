import express from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'follow-graph';
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

async function init() {
  await redis.connect();
  await pg.query(`CREATE TABLE IF NOT EXISTS follows(
    id SERIAL PRIMARY KEY,
    follower_id TEXT NOT NULL,
    followee_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(follower_id, followee_id)
  )`);
  log.info('db init ok');
}

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.post('/follow', async (req, res) => {
  const { follower_id, followee_id } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO follows(follower_id,followee_id) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING *',
      [follower_id, followee_id]);
    await redis.del(`followers:count:${followee_id}`);
    return res.status(201).json(rows[0] || { follower_id, followee_id });
  } catch (e) { log.error('POST /follow', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/followers/:user_id', async (req, res) => {
  try {
    const cacheKey = `followers:count:${req.params.user_id}`;
    const cached = await redis.get(cacheKey);
    const { rows } = await pg.query('SELECT follower_id FROM follows WHERE followee_id=$1', [req.params.user_id]);
    if (!cached) await redis.setEx(cacheKey, 60, String(rows.length));
    return res.json({ user_id: req.params.user_id, count: rows.length, followers: rows.map(r => r.follower_id) });
  } catch (e) { log.error('GET /followers/:user_id', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/following/:user_id', async (req, res) => {
  try {
    const { rows } = await pg.query('SELECT followee_id FROM follows WHERE follower_id=$1', [req.params.user_id]);
    return res.json({ user_id: req.params.user_id, count: rows.length, following: rows.map(r => r.followee_id) });
  } catch (e) { log.error('GET /following/:user_id', e); return res.status(500).json({ error: 'internal error' }); }
});

init().then(() => {
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
}).catch(e => { log.error('init failed', e); process.exit(1); });
