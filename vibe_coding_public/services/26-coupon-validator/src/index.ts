import express from 'express';
import { createClient } from 'redis';

const SERVICE = 'coupon-validator';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const redis = createClient({
  socket: { host: process.env.REDIS_CACHE_HOST || 'redis-cache',
            port: parseInt(process.env.REDIS_CACHE_PORT || '6379'),
            connectTimeout: 2000 },
});
redis.on('error', (e) => log.error('redis error', e));

const app = express();
app.use(express.json());

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.get('/coupons', async (_req, res) => {
  try {
    const keys = await redis.keys('coupon:*');
    const coupons = await Promise.all(keys.map(async (k) => {
      const data = await redis.hGetAll(k);
      return { code: k.replace('coupon:', ''), ...data };
    }));
    return res.json(coupons);
  } catch (e) { log.error('GET /coupons failed', e); return res.status(500).json({ error: 'internal error' }); }
});

app.put('/coupons/:code', async (req, res) => {
  const { code } = req.params;
  const { discount_pct, uses_left } = req.body as { discount_pct: number; uses_left: number };
  try {
    await redis.hSet(`coupon:${code}`, { discount_pct: String(discount_pct), uses_left: String(uses_left) });
    return res.json({ code, discount_pct, uses_left });
  } catch (e) { log.error(`PUT /coupons/${code} failed`, e); return res.status(500).json({ error: 'internal error' }); }
});

app.post('/validate', async (req, res) => {
  const { code, cart_total_cents } = req.body as { code: string; cart_total_cents: number };
  try {
    const data = await redis.hGetAll(`coupon:${code}`);
    if (!data || !data.discount_pct) return res.status(404).json({ valid: false, error: 'coupon not found' });
    const uses = parseInt(data.uses_left || '0');
    if (uses <= 0) return res.status(400).json({ valid: false, error: 'coupon exhausted' });
    const pct = parseInt(data.discount_pct);
    const discount = Math.floor(cart_total_cents * pct / 100);
    await redis.hSet(`coupon:${code}`, 'uses_left', String(uses - 1));
    return res.json({ valid: true, code, discount_cents: discount, discount_pct: pct });
  } catch (e) { log.error('POST /validate failed', e); return res.status(500).json({ error: 'internal error' }); }
});

(async () => {
  await redis.connect();
  log.info('redis connected');
  app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
})();
