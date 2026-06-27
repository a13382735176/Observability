import Fastify from 'fastify';
import { createClient } from 'redis';
import { createHash } from 'crypto';

const SERVICE = 'ab-test-assigner';
const REDIS_HOST = process.env.REDIS_CACHE_HOST || 'redis-cache';
const REDIS_PORT = parseInt(process.env.REDIS_CACHE_PORT || '6379', 10);

const app = Fastify({ logger: false });

const redis = createClient({
  socket: { host: REDIS_HOST, port: REDIS_PORT, connectTimeout: 2000 },
});
redis.on('error', (err: any) => console.error(`${SERVICE}: redis error: ${err.message || err}`));

async function init() {
  try {
    await redis.connect();
    console.log(`${SERVICE}: redis connected`);
  } catch (e: any) {
    console.error(`${SERVICE}: redis connect failed: ${e.message || e}`);
  }
}

app.get('/healthz', async () => ({ status: 'ok', service: SERVICE }));

app.post('/experiments', async (req: any, reply) => {
  try {
    const { name, variants, traffic_pct } = req.body || {};
    if (!name || !Array.isArray(variants) || typeof traffic_pct !== 'number') {
      return reply.code(400).send({ error: 'name, variants[], traffic_pct required' });
    }
    const data = { name, variants, traffic_pct };
    await redis.hSet(`exp:${name}`, 'data', JSON.stringify(data));
    return reply.code(201).send(data);
  } catch (e: any) {
    console.error(`${SERVICE}: POST /experiments: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/experiments/:name', async (req: any, reply) => {
  try {
    const name = req.params.name;
    const raw = await redis.hGet(`exp:${name}`, 'data');
    if (!raw) return reply.code(404).send({ error: 'not found' });
    return reply.send(JSON.parse(raw));
  } catch (e: any) {
    console.error(`${SERVICE}: GET /experiments: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.post('/assign', async (req: any, reply) => {
  try {
    const { experiment_name, user_id } = req.body || {};
    if (!experiment_name || !user_id) {
      return reply.code(400).send({ error: 'experiment_name and user_id required' });
    }
    const raw = await redis.hGet(`exp:${experiment_name}`, 'data');
    if (!raw) return reply.code(404).send({ error: 'experiment not found' });
    const exp = JSON.parse(raw);
    const variants: string[] = exp.variants || [];
    const trafficPct: number = exp.traffic_pct ?? 0;
    const digest = createHash('sha256').update(`${experiment_name}${user_id}`).digest('hex');
    const hashHigh = parseInt(digest.slice(0, 8), 16);
    const hashLow = parseInt(digest.slice(8, 16), 16);
    let variant = 'control';
    if (hashHigh % 100 < trafficPct && variants.length > 0) {
      variant = variants[hashLow % variants.length];
    }
    await redis.sAdd(`assignments:${experiment_name}:${variant}`, String(user_id));
    return reply.send({ experiment_name, user_id, variant });
  } catch (e: any) {
    console.error(`${SERVICE}: POST /assign: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/assignments/:user_id', async (req: any, reply) => {
  try {
    const userId = String(req.params.user_id);
    const expKeys = await redis.keys('exp:*');
    const result: any[] = [];
    for (const ek of expKeys) {
      const name = ek.slice('exp:'.length);
      const raw = await redis.hGet(ek, 'data');
      if (!raw) continue;
      const exp = JSON.parse(raw);
      const variants: string[] = exp.variants || [];
      for (const v of [...variants, 'control']) {
        const isMember = await redis.sIsMember(`assignments:${name}:${v}`, userId);
        if (isMember) {
          result.push({ experiment_name: name, variant: v });
          break;
        }
      }
    }
    return reply.send(result);
  } catch (e: any) {
    console.error(`${SERVICE}: GET /assignments: ${e.message || e}`);
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
