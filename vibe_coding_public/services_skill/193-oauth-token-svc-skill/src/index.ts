import http, { IncomingMessage, ServerResponse } from 'http';
import { randomBytes } from 'crypto';
import { Pool } from 'pg';
import { createClient, RedisClientType } from 'redis';

const SERVICE = 'oauth-token-svc';
const APP_NAME = process.env.APP_NAME || 'oauth-token-svc-skill';
const PORT = Number(process.env.PORT || 8080);
const TOKEN_TTL_SECONDS = 3600;
const MAX_BODY_BYTES = 1024 * 1024;

type JsonValue = Record<string, unknown>;

type CachedToken = {
  client_id: string;
  expires_at: string;
};

const pool = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
});

let redisClient: RedisClientType | undefined;
let redisReady = false;
let shuttingDown = false;

function log(level: 'info' | 'warn' | 'error', message: string, fields: JsonValue = {}) {
  const entry = {
    ts: new Date().toISOString(),
    level,
    service: APP_NAME,
    message,
    ...fields,
  };
  const line = JSON.stringify(entry);
  if (level === 'error') console.error(line);
  else console.log(line);
}

function sendJson(res: ServerResponse, status: number, body: JsonValue) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function notFound(res: ServerResponse) {
  sendJson(res, 404, { error: 'not_found' });
}

function badRequest(res: ServerResponse, message: string) {
  sendJson(res, 400, { error: 'bad_request', message });
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

async function readJsonBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => {
      data += chunk;
      if (Buffer.byteLength(data) > MAX_BODY_BYTES) {
        reject(new Error('request_body_too_large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch (_err) {
        reject(new Error('invalid_json'));
      }
    });
    req.on('error', reject);
  });
}

async function initializeDatabase() {
  await pool.query(`CREATE TABLE IF NOT EXISTS clients(
    id bigserial PRIMARY KEY,
    client_id text UNIQUE,
    client_secret text,
    created_at timestamptz DEFAULT now()
  )`);
  await pool.query(`CREATE TABLE IF NOT EXISTS tokens(
    id bigserial PRIMARY KEY,
    token text UNIQUE,
    client_id text,
    expires_at timestamptz,
    issued_at timestamptz DEFAULT now()
  )`);
}

async function initializeRedis() {
  const host = process.env.REDIS_CACHE_HOST || 'redis-cache';
  const port = Number(process.env.REDIS_CACHE_PORT || 6379);
  const client = createClient({ socket: { host, port } });

  client.on('error', err => {
    redisReady = false;
    log('warn', 'redis client error', { dependency: 'redis-cache', error: err.message });
  });
  client.on('ready', () => {
    redisReady = true;
    log('info', 'redis connected', { dependency: 'redis-cache' });
  });
  client.on('end', () => {
    redisReady = false;
    log('warn', 'redis disconnected', { dependency: 'redis-cache' });
  });

  await client.connect();
  redisClient = client as RedisClientType;
}

function cacheKey(token: string) {
  return `token:${token}`;
}

async function cacheGetToken(token: string): Promise<CachedToken | undefined> {
  if (!redisClient || !redisReady) return undefined;
  try {
    const raw = await redisClient.get(cacheKey(token));
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as CachedToken;
    if (!isText(parsed.client_id) || !isText(parsed.expires_at)) return undefined;
    return parsed;
  } catch (err: any) {
    log('warn', 'cache get failed', { operation: 'introspect', dependency: 'redis-cache', error: err.message });
    return undefined;
  }
}

async function cacheSetToken(token: string, value: CachedToken) {
  if (!redisClient || !redisReady) return;
  try {
    await redisClient.setEx(cacheKey(token), TOKEN_TTL_SECONDS, JSON.stringify(value));
  } catch (err: any) {
    log('warn', 'cache set failed', { operation: 'token', dependency: 'redis-cache', error: err.message });
  }
}

async function cacheDeleteToken(token: string) {
  if (!redisClient || !redisReady) return;
  try {
    await redisClient.del(cacheKey(token));
  } catch (err: any) {
    log('warn', 'cache delete failed', { operation: 'revoke', dependency: 'redis-cache', error: err.message });
  }
}

async function handleToken(req: IncomingMessage, res: ServerResponse) {
  const body = await readJsonBody(req);
  const { client_id, client_secret, grant_type } = body;
  if (!isText(client_id) || !isText(client_secret) || !isText(grant_type)) {
    return badRequest(res, 'client_id, client_secret, and grant_type are required');
  }
  if (grant_type !== 'client_credentials') {
    return sendJson(res, 400, { error: 'unsupported_grant_type' });
  }

  const clientResult = await pool.query(
    'SELECT client_id FROM clients WHERE client_id = $1 AND client_secret = $2',
    [client_id, client_secret]
  );
  if (clientResult.rowCount === 0) {
    log('warn', 'client authentication failed', { operation: 'token' });
    return sendJson(res, 401, { error: 'invalid_client' });
  }

  const token = randomBytes(32).toString('hex');
  const expiresResult = await pool.query(
    `INSERT INTO tokens(token, client_id, expires_at)
     VALUES($1, $2, now() + ($3::int * interval '1 second'))
     RETURNING expires_at`,
    [token, client_id, TOKEN_TTL_SECONDS]
  );
  const expiresAt = expiresResult.rows[0].expires_at instanceof Date
    ? expiresResult.rows[0].expires_at.toISOString()
    : new Date(expiresResult.rows[0].expires_at).toISOString();

  await cacheSetToken(token, { client_id, expires_at: expiresAt });
  sendJson(res, 200, { access_token: token, expires_in: TOKEN_TTL_SECONDS, token_type: 'Bearer' });
}

async function handleIntrospect(req: IncomingMessage, res: ServerResponse) {
  const body = await readJsonBody(req);
  const { token } = body;
  if (!isText(token)) return badRequest(res, 'token is required');

  const cached = await cacheGetToken(token);
  if (cached) {
    const expiresMs = Date.parse(cached.expires_at);
    if (Number.isFinite(expiresMs) && expiresMs > Date.now()) {
      return sendJson(res, 200, { active: true, client_id: cached.client_id, expires_at: cached.expires_at });
    }
    await cacheDeleteToken(token);
  }

  const result = await pool.query(
    'SELECT client_id, expires_at FROM tokens WHERE token = $1 AND expires_at > now()',
    [token]
  );
  if (result.rowCount === 0) return sendJson(res, 200, { active: false });

  const row = result.rows[0];
  const expiresAt = row.expires_at instanceof Date ? row.expires_at.toISOString() : new Date(row.expires_at).toISOString();
  await cacheSetToken(token, { client_id: row.client_id, expires_at: expiresAt });
  sendJson(res, 200, { active: true, client_id: row.client_id, expires_at: expiresAt });
}

async function handleRevoke(req: IncomingMessage, res: ServerResponse) {
  const body = await readJsonBody(req);
  const { token } = body;
  if (!isText(token)) return badRequest(res, 'token is required');

  await pool.query('DELETE FROM tokens WHERE token = $1', [token]);
  await cacheDeleteToken(token);
  sendJson(res, 200, { revoked: true });
}

async function handleClients(req: IncomingMessage, res: ServerResponse) {
  const body = await readJsonBody(req);
  const { client_id, client_secret } = body;
  if (!isText(client_id) || !isText(client_secret)) {
    return badRequest(res, 'client_id and client_secret are required');
  }

  await pool.query(
    `INSERT INTO clients(client_id, client_secret)
     VALUES($1, $2)
     ON CONFLICT (client_id) DO UPDATE SET client_secret = EXCLUDED.client_secret`,
    [client_id, client_secret]
  );
  sendJson(res, 200, { client_id });
}

async function handleActiveTokens(_req: IncomingMessage, res: ServerResponse) {
  const result = await pool.query('SELECT count(*)::int AS active FROM tokens WHERE expires_at > now()');
  sendJson(res, 200, { active: result.rows[0]?.active ?? 0 });
}

async function route(req: IncomingMessage, res: ServerResponse) {
  const start = process.hrtime.bigint();
  const method = req.method || 'GET';
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
  const path = url.pathname;
  let statusCode = 200;

  const originalWriteHead = res.writeHead.bind(res) as any;
  (res.writeHead as any) = (status: number, ...args: any[]) => {
    statusCode = status;
    return originalWriteHead(status, ...args);
  };

  try {
    if (method === 'GET' && path === '/healthz') return sendJson(res, 200, { status: 'ok', service: SERVICE });
    if (method === 'POST' && path === '/token') return await handleToken(req, res);
    if (method === 'POST' && path === '/introspect') return await handleIntrospect(req, res);
    if (method === 'POST' && path === '/revoke') return await handleRevoke(req, res);
    if (method === 'POST' && path === '/clients') return await handleClients(req, res);
    if (method === 'GET' && path === '/tokens/active') return await handleActiveTokens(req, res);
    statusCode = 404;
    return notFound(res);
  } catch (err: any) {
    if (err.message === 'invalid_json') {
      statusCode = 400;
      return badRequest(res, 'invalid JSON');
    }
    if (err.message === 'request_body_too_large') {
      statusCode = 413;
      return sendJson(res, 413, { error: 'request_entity_too_large' });
    }
    statusCode = 500;
    log('error', 'request failed', { operation: `${method} ${path}`, error: err.message });
    return sendJson(res, 500, { error: 'internal_error' });
  } finally {
    const durationMs = Number(process.hrtime.bigint() - start) / 1_000_000;
    log(statusCode >= 500 ? 'error' : 'info', 'request completed', {
      method,
      path,
      status: statusCode,
      duration_ms: Math.round(durationMs),
    });
  }
}

async function shutdown(server: http.Server, signal: string) {
  if (shuttingDown) return;
  shuttingDown = true;
  log('info', 'shutdown started', { signal });
  server.close(async () => {
    try {
      if (redisClient) await redisClient.quit();
      await pool.end();
      log('info', 'shutdown completed', { signal });
      process.exit(0);
    } catch (err: any) {
      log('error', 'shutdown failed', { signal, error: err.message });
      process.exit(1);
    }
  });
  setTimeout(() => process.exit(1), 10_000).unref();
}

async function main() {
  log('info', 'startup started', { port: PORT });
  await initializeDatabase();
  try {
    await initializeRedis();
  } catch (err: any) {
    log('warn', 'redis unavailable at startup', { dependency: 'redis-cache', error: err.message });
  }

  const server = http.createServer(route);
  server.listen(PORT, () => log('info', 'server listening', { port: PORT }));
  process.on('SIGTERM', () => shutdown(server, 'SIGTERM'));
  process.on('SIGINT', () => shutdown(server, 'SIGINT'));
}

main().catch(err => {
  log('error', 'startup failed', { error: err.message });
  process.exit(1);
});
