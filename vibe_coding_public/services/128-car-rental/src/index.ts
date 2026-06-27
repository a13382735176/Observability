import express, { Request, Response } from 'express';
import { Pool } from 'pg';

const SERVICE = 'car-rental';
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
      CREATE TABLE IF NOT EXISTS car_rentals(
        id serial PRIMARY KEY,
        user_id text,
        vehicle_type text,
        pickup_date date,
        return_date date,
        daily_rate_cents int,
        status text DEFAULT 'active',
        created_at timestamptz DEFAULT now()
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

app.post('/rentals', async (req: Request, res: Response) => {
  const { user_id, vehicle_type, pickup_date, return_date, daily_rate_cents } = req.body || {};
  if (!user_id || !vehicle_type || !pickup_date || !return_date || typeof daily_rate_cents !== 'number') {
    return res.status(400).json({ error: 'user_id, vehicle_type, pickup_date, return_date, daily_rate_cents required' });
  }
  try {
    const r = await pool.query(
      `INSERT INTO car_rentals(user_id, vehicle_type, pickup_date, return_date, daily_rate_cents)
       VALUES($1,$2,$3,$4,$5)
       RETURNING id, user_id, vehicle_type, pickup_date, return_date, daily_rate_cents, status, created_at`,
      [user_id, vehicle_type, pickup_date, return_date, daily_rate_cents],
    );
    return res.status(201).json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: POST /rentals: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/rentals/:user_id/active', async (req: Request, res: Response) => {
  try {
    const r = await pool.query(
      `SELECT id, user_id, vehicle_type, pickup_date, return_date, daily_rate_cents, status, created_at
       FROM car_rentals WHERE user_id=$1 AND status='active' ORDER BY id DESC`,
      [req.params.user_id],
    );
    return res.json(r.rows);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /rentals/:user_id/active: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.put('/rentals/:id/return', async (req: Request, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (Number.isNaN(id)) return res.status(400).json({ error: 'invalid id' });
  try {
    const r = await pool.query(
      `UPDATE car_rentals SET status='returned' WHERE id=$1
       RETURNING id, user_id, vehicle_type, pickup_date, return_date, daily_rate_cents, status, created_at`,
      [id],
    );
    if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
    return res.json(r.rows[0]);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: PUT /rentals/:id/return: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

app.get('/rentals', async (_req: Request, res: Response) => {
  try {
    const r = await pool.query(
      `SELECT id, user_id, vehicle_type, pickup_date, return_date, daily_rate_cents, status, created_at
       FROM car_rentals ORDER BY id DESC LIMIT 200`,
    );
    return res.json(r.rows);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: GET /rentals: ${e?.message || e}`);
    return res.status(503).json({ error: 'db error' });
  }
});

initDb().finally(() => {
  app.listen(8080, '0.0.0.0', () => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  });
});
