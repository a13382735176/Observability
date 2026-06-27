import Fastify from 'fastify';
import { createClient } from 'redis';

const SERVICE = 'trending-topics';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const redisCache = createClient({
  socket: { host: process.env.REDIS_CACHE_HOST || 'redis-cache',
            port: parseInt(process.env.REDIS_CACHE_PORT || '6379'),
            connectTimeout: 2000 },
});
redisCache.on('error', (e) => log.error('redis-cache error', e));

const redisStream = createClient({
  socket: { host: process.env.REDIS_STREAM_HOST || 'redis-stream',
            port: parseInt(process.env.REDIS_STREAM_PORT || '6379'),
            connectTimeout: 2000 },
});
redisStream.on('error', (e) => log.error('redis-stream error', e));

const app = Fastify({ logger: false });

app.get('/healthz', async () => ({ status: 'ok', service: SERVICE }));

app.get('/trending', async (_req, reply) => {
  try {
    const items = await redisCache.zRangeWithScores('trending', 0, 9, { REV: true });
    return { trending: items.map(i => ({ topic: i.value, score: i.score })) };
  } catch (e) { log.error('GET /trending', e); return reply.status(500).send({ error: 'internal error' }); }
});

app.post('/signal', async (req: any, reply) => {
  const { topic, weight = 1 } = req.body as { topic: string; weight?: number };
  try {
    await redisCache.zIncrBy('trending', weight, topic);
    await redisStream.xAdd('events:trending', '*', { event: 'topic.signal', topic, weight: String(weight) });
    return { topic, weight, status: 'signaled' };
  } catch (e) { log.error('POST /signal', e); return reply.status(500).send({ error: 'internal error' }); }
});

async function start() {
  await redisCache.connect();
  await redisStream.connect();
  log.info('redis connected');
  await app.listen({ port: 8080, host: '0.0.0.0' });
  log.info('listening on :8080');
}
start().catch(e => { log.error('startup failed', e); process.exit(1); });
