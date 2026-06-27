import Fastify from 'fastify';
import { Pool } from 'pg';

const SERVICE = 'cohort-builder';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';

const app = Fastify({ logger: false });

const pool = new Pool({
  connectionString: PG_DSN,
  connectionTimeoutMillis: 2000,
  statement_timeout: 2000,
  query_timeout: 2000,
  max: 4,
});
pool.on('error', (err: any) => console.error(`${SERVICE}: pg pool error: ${err.message || err}`));

const EVENT_TYPES = ['page_view', 'click', 'purchase', 'signup', 'logout'];

async function init() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS cohorts(
        id bigserial PRIMARY KEY,
        name text,
        criteria jsonb,
        created_at timestamptz DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS cohort_members(
        id bigserial PRIMARY KEY,
        cohort_id bigint,
        user_id text,
        added_at timestamptz DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS usage_events_fake(
        id bigserial PRIMARY KEY,
        user_id text,
        event_type text,
        ts timestamptz DEFAULT now()
      )
    `);
    const c = await pool.query('SELECT count(*)::int AS c FROM usage_events_fake');
    if (c.rows[0].c === 0) {
      for (let i = 0; i < 50; i++) {
        const uid = `user_${(i % 12) + 1}`;
        const ev = EVENT_TYPES[i % EVENT_TYPES.length];
        const daysAgo = i % 30;
        await pool.query(
          `INSERT INTO usage_events_fake(user_id, event_type, ts) VALUES($1, $2, now() - ($3 || ' days')::interval)`,
          [uid, ev, String(daysAgo)]
        );
      }
      console.log(`${SERVICE}: pre-populated 50 sample rows`);
    }
    console.log(`${SERVICE}: postgres ready`);
  } catch (e: any) {
    console.error(`${SERVICE}: postgres init failed: ${e.message || e}`);
  }
}

app.get('/healthz', async () => ({ status: 'ok', service: SERVICE }));

app.post('/cohorts', async (req: any, reply) => {
  try {
    const { name, criteria } = req.body || {};
    if (!name || !criteria || typeof criteria !== 'object') {
      return reply.code(400).send({ error: 'name and criteria required' });
    }
    const { event_type, min_count, since_days } = criteria;
    if (!event_type || typeof min_count !== 'number' || typeof since_days !== 'number') {
      return reply.code(400).send({ error: 'criteria.event_type, min_count, since_days required' });
    }
    const r = await pool.query(
      'INSERT INTO cohorts(name, criteria) VALUES($1, $2::jsonb) RETURNING id, name, criteria, created_at',
      [name, JSON.stringify(criteria)]
    );
    return reply.code(201).send(r.rows[0]);
  } catch (e: any) {
    console.error(`${SERVICE}: POST /cohorts: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.post('/cohorts/:id/evaluate', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const c = await pool.query('SELECT id, criteria FROM cohorts WHERE id=$1', [id]);
    if (c.rowCount === 0) return reply.code(404).send({ error: 'cohort not found' });
    const criteria = c.rows[0].criteria;
    const { event_type, min_count, since_days } = criteria;

    const matches = await pool.query(
      `SELECT user_id, count(*)::int AS cnt
         FROM usage_events_fake
         WHERE event_type=$1 AND ts > now() - ($2 || ' days')::interval
         GROUP BY user_id
         HAVING count(*) >= $3`,
      [event_type, String(since_days), min_count]
    );

    let added = 0;
    for (const row of matches.rows) {
      await pool.query(
        'INSERT INTO cohort_members(cohort_id, user_id) VALUES($1, $2)',
        [id, row.user_id]
      );
      added++;
    }
    return reply.send({ cohort_id: Number(id), member_count: added });
  } catch (e: any) {
    console.error(`${SERVICE}: POST /cohorts/:id/evaluate: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/cohorts/:id', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const c = await pool.query(
      'SELECT id, name, criteria, created_at FROM cohorts WHERE id=$1',
      [id]
    );
    if (c.rowCount === 0) return reply.code(404).send({ error: 'not found' });
    const m = await pool.query(
      'SELECT count(*)::int AS c FROM cohort_members WHERE cohort_id=$1',
      [id]
    );
    return reply.send({ ...c.rows[0], member_count: m.rows[0].c });
  } catch (e: any) {
    console.error(`${SERVICE}: GET /cohorts/:id: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/cohorts/:id/members', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const limit = Math.min(parseInt(req.query?.limit ?? '100', 10) || 100, 1000);
    const r = await pool.query(
      'SELECT id, cohort_id, user_id, added_at FROM cohort_members WHERE cohort_id=$1 ORDER BY id LIMIT $2',
      [id, limit]
    );
    return reply.send({ cohort_id: Number(id), members: r.rows });
  } catch (e: any) {
    console.error(`${SERVICE}: GET /cohorts/:id/members: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/cohorts', async (_req, reply) => {
  try {
    const r = await pool.query(
      'SELECT id, name, criteria, created_at FROM cohorts ORDER BY id DESC'
    );
    return reply.send({ cohorts: r.rows });
  } catch (e: any) {
    console.error(`${SERVICE}: GET /cohorts: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

init().finally(() => {
  app.listen({ host: '0.0.0.0', port: 8080 }).then(() => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  }).catch((e) => {
    console.error(`${SERVICE}: listen failed: ${e.message || e}`);
    process.exit(1);
  });
});
