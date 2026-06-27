import express, { Request, Response } from 'express';
import { Pool } from 'pg';

const SERVICE = 'cron-svc';
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
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id bigserial PRIMARY KEY,
                name text,
                expression text,
                action_url text,
                enabled boolean DEFAULT true,
                next_run_at timestamptz DEFAULT now(),
                created_at timestamptz DEFAULT now()
            )
        `);
        await pool.query(`
            CREATE TABLE IF NOT EXISTS cron_runs (
                id bigserial PRIMARY KEY,
                cron_id bigint,
                ran_at timestamptz DEFAULT now(),
                status text,
                error text
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

app.post('/cron', async (req: Request, res: Response) => {
    const { name, expression, action_url } = req.body || {};
    if (!name || !expression || !action_url) {
        return res.status(400).json({ error: 'name, expression, action_url required' });
    }
    try {
        const r = await pool.query(
            `INSERT INTO cron_jobs(name, expression, action_url, enabled, next_run_at)
             VALUES($1, $2, $3, true, now() + interval '60 seconds')
             RETURNING id, name, expression, action_url, enabled, next_run_at, created_at`,
            [name, expression, action_url]
        );
        res.status(201).json(r.rows[0]);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: POST /cron: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/cron/due', async (_req: Request, res: Response) => {
    try {
        const r = await pool.query(
            `SELECT id, name, expression, action_url, enabled, next_run_at, created_at
             FROM cron_jobs
             WHERE next_run_at <= now() AND enabled = true
             ORDER BY next_run_at ASC
             LIMIT 50`
        );
        res.json(r.rows);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: GET /cron/due: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/cron/:id', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(
            `SELECT id, name, expression, action_url, enabled, next_run_at, created_at
             FROM cron_jobs WHERE id = $1`,
            [id]
        );
        if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
        res.json(r.rows[0]);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: GET /cron/${id}: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.put('/cron/:id/enable', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(
            `UPDATE cron_jobs SET enabled = true WHERE id = $1
             RETURNING id, name, expression, action_url, enabled, next_run_at, created_at`,
            [id]
        );
        if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
        res.json(r.rows[0]);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: PUT /cron/${id}/enable: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.put('/cron/:id/disable', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(
            `UPDATE cron_jobs SET enabled = false WHERE id = $1
             RETURNING id, name, expression, action_url, enabled, next_run_at, created_at`,
            [id]
        );
        if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
        res.json(r.rows[0]);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: PUT /cron/${id}/disable: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.post('/cron/:id/log', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    const { status, error } = req.body || {};
    if (!status) return res.status(400).json({ error: 'status required' });
    try {
        const job = await pool.query(`SELECT id FROM cron_jobs WHERE id = $1`, [id]);
        if (job.rowCount === 0) return res.status(404).json({ error: 'not found' });
        const ins = await pool.query(
            `INSERT INTO cron_runs(cron_id, status, error)
             VALUES($1, $2, $3)
             RETURNING id, cron_id, ran_at, status, error`,
            [id, status, error ?? null]
        );
        await pool.query(
            `UPDATE cron_jobs SET next_run_at = now() + interval '60 seconds' WHERE id = $1`,
            [id]
        );
        res.status(201).json(ins.rows[0]);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: POST /cron/${id}/log: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/cron/:id/runs', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(
            `SELECT id, cron_id, ran_at, status, error
             FROM cron_runs WHERE cron_id = $1
             ORDER BY id DESC LIMIT 20`,
            [id]
        );
        res.json(r.rows);
    } catch (e: any) {
        console.error(`ERROR ${SERVICE}: GET /cron/${id}/runs: ${e?.message || e}`);
        res.status(503).json({ error: 'db error' });
    }
});

initDb().finally(() => {
    app.listen(8080, '0.0.0.0', () => {
        console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
    });
});
