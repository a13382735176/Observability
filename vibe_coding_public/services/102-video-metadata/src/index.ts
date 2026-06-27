import express from 'express';
import { Pool } from 'pg';

const SERVICE = 'video-metadata';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE}:`, m, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const app = express();
app.use(express.json());

async function init() {
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS videos(
      id SERIAL PRIMARY KEY,
      title TEXT NOT NULL,
      duration_s INT NOT NULL,
      url TEXT NOT NULL,
      tags JSONB DEFAULT '[]',
      created_at TIMESTAMPTZ DEFAULT NOW()
    )`);
    log.info('postgres ready');
  } catch (e) { log.error('postgres init failed', e); }
}

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.post('/videos', async (req, res) => {
  const { title, duration_s, url, tags } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO videos(title,duration_s,url,tags) VALUES($1,$2,$3,$4::jsonb) RETURNING *',
      [title, duration_s, url, JSON.stringify(tags || [])]);
    return res.status(201).json(rows[0]);
  } catch (e) { log.error('POST /videos failed', e); return res.status(502).json({ error: 'postgres error' }); }
});

app.get('/videos/:id', async (req, res) => {
  try {
    const { rows } = await pg.query('SELECT * FROM videos WHERE id=$1', [req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'not found' });
    return res.json(rows[0]);
  } catch (e) { log.error('GET /videos/:id failed', e); return res.status(502).json({ error: 'postgres error' }); }
});

app.get('/videos', async (req, res) => {
  const tag = req.query.tag as string | undefined;
  try {
    let rows;
    if (tag) {
      const r = await pg.query("SELECT * FROM videos WHERE tags @> $1::jsonb ORDER BY id", [JSON.stringify([tag])]);
      rows = r.rows;
    } else {
      const r = await pg.query('SELECT * FROM videos ORDER BY id DESC LIMIT 50');
      rows = r.rows;
    }
    return res.json(rows);
  } catch (e) { log.error('GET /videos failed', e); return res.status(502).json({ error: 'postgres error' }); }
});

init().then(() => {
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
});
