import http, { IncomingMessage, ServerResponse } from 'node:http';
import { Pool } from 'pg';

const APP_NAME = process.env.APP_NAME || 'file-metadata-skill';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';
const PORT = Number(process.env.PORT || 8080);

const schemaSql = `
CREATE TABLE IF NOT EXISTS file_metadata (
  id bigserial PRIMARY KEY,
  filename text,
  mime_type text,
  size_bytes bigint,
  sha256 text,
  owner_id text,
  uploaded_at timestamptz DEFAULT now()
)`;

const pool = new Pool({ connectionString: PG_DSN });
let dbReady = false;
let shuttingDown = false;

type LogLevel = 'info' | 'warn' | 'error';

function log(level: LogLevel, event: string, fields: Record<string, unknown> = {}): void {
  const entry = {
    ts: new Date().toISOString(),
    level,
    service: APP_NAME,
    event,
    ...fields,
  };
  const line = JSON.stringify(entry);
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.log(line);
}

function requestId(req: IncomingMessage): string {
  const header = req.headers['x-request-id'];
  if (Array.isArray(header)) return header[0] || randomId();
  return header || randomId();
}

function randomId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  const data = JSON.stringify(body);
  res.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(data),
  });
  res.end(data);
}

async function initializeDatabase(): Promise<void> {
  const started = Date.now();
  try {
    await pool.query(schemaSql);
    dbReady = true;
    log('info', 'database_schema_ready', {
      operation: 'startup',
      dependency: 'postgres',
      latency_ms: Date.now() - started,
    });
  } catch (error) {
    dbReady = false;
    log('error', 'database_schema_failed', {
      operation: 'startup',
      dependency: 'postgres',
      latency_ms: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

async function checkDatabase(): Promise<boolean> {
  const started = Date.now();
  try {
    await pool.query('SELECT 1');
    dbReady = true;
    log('info', 'dependency_check_ok', {
      operation: 'healthz',
      dependency: 'postgres',
      latency_ms: Date.now() - started,
    });
    return true;
  } catch (error) {
    dbReady = false;
    log('warn', 'dependency_check_failed', {
      operation: 'healthz',
      dependency: 'postgres',
      latency_ms: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
    return false;
  }
}

async function handleHealthz(res: ServerResponse): Promise<void> {
  if (shuttingDown) {
    sendJson(res, 503, { status: 'shutting_down', service: APP_NAME });
    return;
  }

  const ok = dbReady ? true : await checkDatabase();
  sendJson(res, ok ? 200 : 503, {
    status: ok ? 'ok' : 'degraded',
    service: APP_NAME,
    postgres: ok ? 'ok' : 'unavailable',
  });
}

async function route(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const started = Date.now();
  const id = requestId(req);
  const method = req.method || 'UNKNOWN';
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  res.setHeader('x-request-id', id);

  try {
    if (method === 'GET' && url.pathname === '/healthz') {
      await handleHealthz(res);
      return;
    }

    sendJson(res, 404, { error: 'not_found' });
  } catch (error) {
    log('error', 'request_failed', {
      request_id: id,
      method,
      path: url.pathname,
      latency_ms: Date.now() - started,
      error: error instanceof Error ? error.message : String(error),
    });
    if (!res.headersSent) sendJson(res, 500, { error: 'internal_error' });
  } finally {
    log('info', 'request_completed', {
      request_id: id,
      method,
      path: url.pathname,
      status_code: res.statusCode,
      latency_ms: Date.now() - started,
    });
  }
}

const server = http.createServer((req, res) => {
  void route(req, res);
});

server.on('clientError', (error, socket) => {
  log('warn', 'client_error', { error: error.message });
  socket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
});

async function start(): Promise<void> {
  log('info', 'service_starting', { port: PORT });
  await initializeDatabase();
  server.listen(PORT, () => {
    log('info', 'service_listening', { port: PORT });
  });
}

async function shutdown(signal: NodeJS.Signals): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  log('info', 'service_stopping', { signal });

  server.close(async (error?: Error) => {
    if (error) log('error', 'server_close_failed', { error: error.message });
    try {
      await pool.end();
      log('info', 'database_pool_closed', { dependency: 'postgres' });
      process.exit(error ? 1 : 0);
    } catch (poolError) {
      log('error', 'database_pool_close_failed', {
        dependency: 'postgres',
        error: poolError instanceof Error ? poolError.message : String(poolError),
      });
      process.exit(1);
    }
  });
}

process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('SIGINT', () => void shutdown('SIGINT'));

process.on('unhandledRejection', (reason) => {
  log('error', 'unhandled_rejection', { error: reason instanceof Error ? reason.message : String(reason) });
});

process.on('uncaughtException', (error) => {
  log('error', 'uncaught_exception', { error: error.message });
  void shutdown('SIGTERM');
});

void start().catch((error) => {
  log('error', 'service_start_failed', { error: error instanceof Error ? error.message : String(error) });
  process.exit(1);
});
