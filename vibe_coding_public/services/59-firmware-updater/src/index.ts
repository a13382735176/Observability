import express from 'express';
import { Pool } from 'pg';
import { createClient } from 'redis';

const SERVICE = 'firmware-updater';
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
  await pg.query(`CREATE TABLE IF NOT EXISTS firmware_updates(
    id SERIAL PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    changelog TEXT,
    artifact_url TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
  )`);
  await pg.query(`CREATE TABLE IF NOT EXISTS device_updates(
    id SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMPTZ DEFAULT NOW()
  )`);
  log.info('db init ok');
}

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.post('/updates', async (req, res) => {
  const { version, changelog, artifact_url } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO firmware_updates(version,changelog,artifact_url) VALUES($1,$2,$3) ON CONFLICT(version) DO UPDATE SET changelog=$2, artifact_url=$3 RETURNING *',
      [version, changelog || '', artifact_url]);
    await redis.del('firmware:latest');
    return res.status(201).json(rows[0]);
  } catch (e) { log.error('POST /updates', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/updates/latest', async (_req, res) => {
  try {
    const cached = await redis.get('firmware:latest');
    if (cached) return res.json(JSON.parse(cached));
    const { rows } = await pg.query('SELECT * FROM firmware_updates ORDER BY created_at DESC LIMIT 1');
    if (!rows[0]) return res.status(404).json({ error: 'no updates' });
    await redis.setEx('firmware:latest', 60, JSON.stringify(rows[0]));
    return res.json(rows[0]);
  } catch (e) { log.error('GET /updates/latest', e); return res.status(500).json({ error: 'internal error' }); }
});

app.post('/devices/:device_id/update', async (req, res) => {
  const { device_id } = req.params;
  const { version } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO device_updates(device_id,version,status) VALUES($1,$2,$3) RETURNING *',
      [device_id, version, 'in_progress']);
    await redis.set(`device:update:${device_id}`, JSON.stringify({ version, status: 'in_progress' }), { EX: 3600 });
    return res.status(201).json(rows[0]);
  } catch (e) { log.error('POST /devices/:device_id/update', e); return res.status(500).json({ error: 'internal error' }); }
});

init().then(() => {
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
}).catch(e => { log.error('init failed', e); process.exit(1); });
