import express, { Request, Response } from 'express';
import { createClient } from 'redis';

const SERVICE = 'shipping-quote';
const REDIS_CACHE_HOST = process.env.REDIS_CACHE_HOST || 'redis-cache';
const REDIS_CACHE_PORT = parseInt(process.env.REDIS_CACHE_PORT || '6379', 10);
const UPSTREAM_URL = process.env.UPSTREAM_URL || 'http://mock-upstream:8080';

const app = express();
app.use(express.json());

const redis = createClient({
  socket: {
    host: REDIS_CACHE_HOST,
    port: REDIS_CACHE_PORT,
    connectTimeout: 2000,
  },
});
redis.on('error', (err: any) => {
  console.error(`ERROR ${SERVICE}: redis error: ${err?.message || err}`);
});

app.get('/healthz', (_req: Request, res: Response) => {
  res.json({ status: 'ok', service: SERVICE });
});

app.post('/quote', async (req: Request, res: Response) => {
  const { origin_zip, dest_zip, weight_kg } = req.body || {};
  if (!origin_zip || !dest_zip || typeof weight_kg !== 'number') {
    return res.status(400).json({ error: 'origin_zip, dest_zip, weight_kg required' });
  }
  const cacheKey = 'ship:' + origin_zip + ':' + dest_zip + ':' + weight_kg;

  try {
    const cached = await redis.get(cacheKey);
    if (cached) {
      try {
        return res.json({ source: 'cache', data: JSON.parse(cached) });
      } catch {
        return res.json({ source: 'cache', data: { raw: cached } });
      }
    }
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: cache get ${cacheKey}: ${e?.message || e}`);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2000);
  try {
    const resp = await fetch(`${UPSTREAM_URL}/shipping`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ origin_zip, dest_zip, weight_kg }),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) {
      console.error(`ERROR ${SERVICE}: upstream status ${resp.status}`);
      return res.status(502).json({ error: 'upstream error' });
    }
    const result = await resp.json() as { rate_cents: number };
    try {
      await redis.setEx(cacheKey, 300, JSON.stringify(result));
    } catch (e: any) {
      console.error(`ERROR ${SERVICE}: cache setex ${cacheKey}: ${e?.message || e}`);
    }
    return res.json({ source: 'upstream', data: result });
  } catch (e: any) {
    clearTimeout(timer);
    console.error(`ERROR ${SERVICE}: upstream call: ${e?.message || e}`);
    return res.status(502).json({ error: 'upstream error' });
  }
});

app.post('/quote/refresh', async (_req: Request, res: Response) => {
  try {
    let cursor = 0;
    let deleted = 0;
    do {
      const reply: any = await redis.scan(cursor, { MATCH: 'ship:*', COUNT: 100 });
      cursor = Number(reply.cursor);
      const keys: string[] = reply.keys || [];
      if (keys.length > 0) {
        deleted += await redis.del(keys);
      }
    } while (cursor !== 0);
    return res.json({ ok: true, deleted });
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: refresh scan/del: ${e?.message || e}`);
    return res.status(503).json({ error: 'cache error' });
  }
});

app.get('/quote/cached', async (_req: Request, res: Response) => {
  try {
    const out: Array<{ key: string; value: any }> = [];
    let cursor = 0;
    do {
      const reply: any = await redis.scan(cursor, { MATCH: 'ship:*', COUNT: 100 });
      cursor = Number(reply.cursor);
      const keys: string[] = reply.keys || [];
      for (const k of keys) {
        try {
          const v = await redis.get(k);
          let parsed: any = v;
          if (v) {
            try { parsed = JSON.parse(v); } catch { parsed = v; }
          }
          out.push({ key: k, value: parsed });
        } catch (e: any) {
          console.error(`ERROR ${SERVICE}: cache get ${k}: ${e?.message || e}`);
        }
      }
    } while (cursor !== 0);
    return res.json(out);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: cached scan: ${e?.message || e}`);
    return res.status(503).json({ error: 'cache error' });
  }
});

(async () => {
  try {
    await redis.connect();
    console.log(`${SERVICE}: redis connected`);
  } catch (e: any) {
    console.error(`ERROR ${SERVICE}: redis connect failed: ${e?.message || e}`);
  }
  app.listen(8080, '0.0.0.0', () => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  });
})();
