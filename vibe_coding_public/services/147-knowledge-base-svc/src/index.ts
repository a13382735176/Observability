import express, { Request, Response } from 'express';
import { Pool } from 'pg';

const SERVICE = 'knowledge-base-svc';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';

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

async function initDb() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS kb_articles(
        id bigserial PRIMARY KEY,
        title text NOT NULL,
        body text NOT NULL,
        tags text[] NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz
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

app.post('/articles', async (req: Request, res: Response) => {
  const { title, body, tags } = req.body || {};
  if (typeof title !== 'string' || typeof body !== 'string') {
    return res.status(400).json({ error: 'title and body required' });
  }
  const tagsArr: string[] = Array.isArray(tags) ? tags.map((t: any) => String(t)) : [];
  try {
    const r = await pool.query(
      `INSERT INTO kb_articles(title, body, tags)
       VALUES($1, $2, $3)
       RETURNING id, title, body, tags, created_at, updated_at`,
      [title, body, tagsArr],
    );
    return res.status(201).json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /articles: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/articles/search', async (req: Request, res: Response) => {
  const q = String(req.query.q || '').trim();
  if (!q) return res.status(400).json({ error: 'q required' });
  try {
    const like = `%${q}%`;
    const r = await pool.query(
      `SELECT id, title, body, tags, created_at, updated_at
       FROM kb_articles
       WHERE title ILIKE $1 OR body ILIKE $1
       ORDER BY id DESC LIMIT 20`,
      [like],
    );
    return res.json(r.rows);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /articles/search: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/articles', async (req: Request, res: Response) => {
  const tag = req.query.tag ? String(req.query.tag) : null;
  try {
    let r;
    if (tag) {
      r = await pool.query(
        `SELECT id, title, body, tags, created_at, updated_at
         FROM kb_articles WHERE $1 = ANY(tags)
         ORDER BY id DESC LIMIT 100`,
        [tag],
      );
    } else {
      r = await pool.query(
        `SELECT id, title, body, tags, created_at, updated_at
         FROM kb_articles ORDER BY id DESC LIMIT 100`,
      );
    }
    return res.json(r.rows);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /articles: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/articles/:id', async (req: Request, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (Number.isNaN(id)) return res.status(400).json({ error: 'invalid id' });
  try {
    const r = await pool.query(
      `SELECT id, title, body, tags, created_at, updated_at
       FROM kb_articles WHERE id=$1`,
      [id],
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    return res.json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /articles/:id: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.put('/articles/:id', async (req: Request, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (Number.isNaN(id)) return res.status(400).json({ error: 'invalid id' });
  const { title, body, tags } = req.body || {};
  const sets: string[] = [];
  const params: any[] = [];
  let idx = 1;
  if (typeof title === 'string') { sets.push(`title=$${idx++}`); params.push(title); }
  if (typeof body === 'string') { sets.push(`body=$${idx++}`); params.push(body); }
  if (Array.isArray(tags)) { sets.push(`tags=$${idx++}`); params.push(tags.map((t: any) => String(t))); }
  if (sets.length === 0) return res.status(400).json({ error: 'no fields to update' });
  sets.push(`updated_at=now()`);
  params.push(id);
  try {
    const r = await pool.query(
      `UPDATE kb_articles SET ${sets.join(', ')} WHERE id=$${idx}
       RETURNING id, title, body, tags, created_at, updated_at`,
      params,
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    return res.json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: PUT /articles/:id: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

initDb().finally(() => {
  app.listen(8080, '0.0.0.0', () => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  });
});
