import Fastify from 'fastify';
import { createClient } from 'redis';

const SERVICE = 'recommendation-api';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const cache = createClient({
  socket: { host: process.env.REDIS_CACHE_HOST || 'redis-cache',
            port: parseInt(process.env.REDIS_CACHE_PORT || '6379'),
            connectTimeout: 2000 },
});
cache.on('error', (e) => log.error('redis-cache error', e));

const stream = createClient({
  socket: { host: process.env.REDIS_STREAM_HOST || 'redis-stream',
            port: parseInt(process.env.REDIS_STREAM_PORT || '6379'),
            connectTimeout: 2000 },
});
stream.on('error', (e) => log.error('redis-stream error', e));

const app = Fastify({ logger: false });

app.get('/healthz', async () => ({ status: 'ok', service: SERVICE }));

app.get('/recommendations/:user_id', async (req, reply) => {
  const { user_id } = req.params as { user_id: string };
  try {
    const key = `recs:${user_id}`;
    const cached = await cache.get(key);
    if (cached) return reply.send(JSON.parse(cached));
    const events = await stream.xRevRange('events:recommend', '+', '-', { COUNT: 20 });
    const skus: string[] = [...new Set(
      events.map((e) => (e.message as Record<string, string>).product_id).filter(Boolean)
    )].slice(0, 5);
    const result = { user_id, product_ids: skus };
    await cache.setEx(key, 60, JSON.stringify(result));
    return reply.send(result);
  } catch (e) { log.error('GET /recommendations failed', e); return reply.status(500).send({ error: 'internal error' }); }
});

app.post('/events', async (req, reply) => {
  const { product_id, user_id } = req.body as { product_id: string; user_id: string };
  try {
    await stream.xAdd('events:recommend', '*', { product_id: product_id || '', user_id: user_id || '' });
    return reply.status(201).send({ ok: true });
  } catch (e) { log.error('POST /events failed', e); return reply.status(500).send({ error: 'internal error' }); }
});

(async () => {
  await cache.connect();
  await stream.connect();
  await app.listen({ port: 8080, host: '0.0.0.0' });
  log.info('listening on :8080');
})();
