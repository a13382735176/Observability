import http, { IncomingMessage, ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import { Pool } from 'pg';
import { createClient, RedisClientType } from 'redis';

const APP_NAME = process.env.APP_NAME || 'event-enricher-skill';
const PORT = Number.parseInt(process.env.PORT || '8080', 10);
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const REDIS_STREAM_HOST = process.env.REDIS_STREAM_HOST || 'redis-stream';
const REDIS_STREAM_PORT = Number.parseInt(process.env.REDIS_STREAM_PORT || '6379', 10);

const schemaSql = `
CREATE TABLE IF NOT EXISTS enrich_events(
  id BIGSERIAL PRIMARY KEY,
  tenant TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  enriched JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)`;

type LogLevel = 'info' | 'warn' | 'error';

type LogFields = Record<string, string | number | boolean | null | undefined>;

const pool = new Pool({ connectionString: PG_DSN });
const redis: RedisClientType = createClient({
  socket: {
    host: REDIS_STREAM_HOST,
    port: REDIS_STREAM_PORT,
    reconnectStrategy: false,
  },
});

let acceptingTraffic = false;
let shuttingDown = false;
let redisConnected = false;

function log(level: LogLevel, message: string, fields: LogFields = {}): void {
  const entry = {
    ts: new Date().toISOString(),
    level,
    service: APP_NAME,
    message,
    ...fields,
  };
  const line = JSON.stringify(entry);
  if (level === 'error') {
    console.error(line);
  } else if (level === 'warn') {
    console.warn(line);
  } else {
    console.log(line);
  }
}

function durationMs(startedAt: bigint): number {
  return Number(process.hrtime.bigint() - startedAt) / 1_000_000;
}

function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  const encoded = JSON.stringify(body);
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(encoded),
  });
  res.end(encoded);
}

async function ensureSchema(): Promise<void> {
  const startedAt = process.hrtime.bigint();
  log('info', 'database schema initialization started', { operation: 'db.schema.init' });
  await pool.query(schemaSql);
  log('info', 'database schema initialization completed', {
    operation: 'db.schema.init',
    duration_ms: Math.round(durationMs(startedAt)),
  });
}

async function connectRedis(): Promise<void> {
  const startedAt = process.hrtime.bigint();
  log('info', 'redis connection started', { operation: 'redis.connect' });
  await redis.connect();
  redisConnected = true;
  log('info', 'redis connection completed', {
    operation: 'redis.connect',
    duration_ms: Math.round(durationMs(startedAt)),
  });
}

async function checkPostgres(): Promise<'ok' | 'error'> {
  try {
    await pool.query('SELECT 1');
    return 'ok';
  } catch (error) {
    log('warn', 'postgres health check failed', {
      operation: 'health.postgres',
      error: error instanceof Error ? error.message : String(error),
    });
    return 'error';
  }
}

async function checkRedis(): Promise<'ok' | 'error'> {
  try {
    if (!redisConnected || !redis.isOpen) {
      return 'error';
    }
    await redis.ping();
    return 'ok';
  } catch (error) {
    log('warn', 'redis health check failed', {
      operation: 'health.redis',
      error: error instanceof Error ? error.message : String(error),
    });
    return 'error';
  }
}

async function handleHealthz(req: IncomingMessage, res: ServerResponse, requestId: string): Promise<void> {
  const startedAt = process.hrtime.bigint();
  const [postgres, redisStatus] = await Promise.all([checkPostgres(), checkRedis()]);
  const ready = acceptingTraffic && !shuttingDown && postgres === 'ok' && redisStatus === 'ok';
  const statusCode = ready ? 200 : 503;

  sendJson(res, statusCode, {
    status: ready ? 'ok' : 'unavailable',
    service: APP_NAME,
    dependencies: {
      postgres,
      redis_stream: redisStatus,
    },
  });

  log(statusCode === 200 ? 'info' : 'warn', 'health check completed', {
    operation: 'http.healthz',
    request_id: requestId,
    status_code: statusCode,
    duration_ms: Math.round(durationMs(startedAt)),
  });
}

async function requestHandler(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const requestId = req.headers['x-request-id']?.toString() || randomUUID();
  res.setHeader('x-request-id', requestId);

  try {
    if (req.method === 'GET' && req.url === '/healthz') {
      await handleHealthz(req, res, requestId);
      return;
    }

    sendJson(res, 404, { error: 'not_found' });
  } catch (error) {
    log('error', 'request handling failed', {
      operation: 'http.request',
      request_id: requestId,
      method: req.method || null,
      path: req.url || null,
      error: error instanceof Error ? error.message : String(error),
    });
    if (!res.headersSent) {
      sendJson(res, 500, { error: 'internal_error' });
    } else {
      res.end();
    }
  }
}

const server = http.createServer((req, res) => {
  void requestHandler(req, res);
});

async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  acceptingTraffic = false;
  log('info', 'shutdown started', { operation: 'service.shutdown', signal });

  await new Promise<void>((resolve) => server.close(() => resolve()));

  try {
    if (redisConnected && redis.isOpen) {
      await redis.quit();
    }
  } catch (error) {
    log('warn', 'redis shutdown failed', {
      operation: 'redis.shutdown',
      error: error instanceof Error ? error.message : String(error),
    });
  }

  try {
    await pool.end();
  } catch (error) {
    log('warn', 'postgres shutdown failed', {
      operation: 'postgres.shutdown',
      error: error instanceof Error ? error.message : String(error),
    });
  }

  log('info', 'shutdown completed', { operation: 'service.shutdown' });
}

async function main(): Promise<void> {
  log('info', 'service startup started', { operation: 'service.startup', port: PORT });
  redis.on('error', (error) => {
    redisConnected = false;
    log('warn', 'redis client error', {
      operation: 'redis.client',
      error: error instanceof Error ? error.message : String(error),
    });
  });

  try {
    await ensureSchema();
    await connectRedis();
  } catch (error) {
    log('error', 'service startup failed', {
      operation: 'service.startup',
      error: error instanceof Error ? error.message : String(error),
    });
    await pool.end().catch(() => undefined);
    if (redis.isOpen) {
      await redis.quit().catch(() => undefined);
    }
    process.exit(1);
  }

  server.listen(PORT, () => {
    acceptingTraffic = true;
    log('info', 'service listening', { operation: 'service.listen', port: PORT });
  });
}

process.on('SIGTERM', () => {
  void shutdown('SIGTERM').then(() => process.exit(0));
});

process.on('SIGINT', () => {
  void shutdown('SIGINT').then(() => process.exit(0));
});

process.on('uncaughtException', (error) => {
  log('error', 'uncaught exception', { operation: 'process.uncaught_exception', error: error.message });
  void shutdown('uncaughtException').finally(() => process.exit(1));
});

process.on('unhandledRejection', (reason) => {
  log('error', 'unhandled rejection', {
    operation: 'process.unhandled_rejection',
    error: reason instanceof Error ? reason.message : String(reason),
  });
  void shutdown('unhandledRejection').finally(() => process.exit(1));
});

void main();
