import Hapi from '@hapi/hapi';
import { Pool } from 'pg';

const SERVICE = 'product-variant';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const init = async () => {
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS variants (
      id SERIAL PRIMARY KEY, product_id INT NOT NULL,
      color TEXT, size TEXT, price_delta_cents INT DEFAULT 0,
      created_at TIMESTAMPTZ DEFAULT NOW())`);
    log.info('postgres ready');
  } catch (e) { log.error('postgres init failed', e); }

  const server = Hapi.server({ host: '0.0.0.0', port: 8080 });

  server.route({ method: 'GET', path: '/healthz',
    handler: () => ({ status: 'ok', service: SERVICE }) });

  server.route({ method: 'GET', path: '/variants/{product_id}',
    handler: async (req, h) => {
      try {
        const { rows } = await pg.query(
          'SELECT * FROM variants WHERE product_id=$1 ORDER BY id',
          [req.params.product_id]);
        return rows;
      } catch (e) { log.error('GET /variants failed', e); return h.response({ error: 'internal error' }).code(500); }
    }
  });

  server.route({ method: 'POST', path: '/variants',
    handler: async (req, h) => {
      const { product_id, color, size, price_delta_cents } = req.payload as any;
      try {
        const { rows } = await pg.query(
          'INSERT INTO variants(product_id,color,size,price_delta_cents) VALUES($1,$2,$3,$4) RETURNING *',
          [product_id, color || '', size || '', price_delta_cents || 0]);
        return h.response(rows[0]).code(201);
      } catch (e) { log.error('POST /variants failed', e); return h.response({ error: 'internal error' }).code(500); }
    }
  });

  await server.start();
  log.info('listening on :8080');
};

process.on('unhandledRejection', (e) => { log.error('unhandled rejection', e); process.exit(1); });
init();
