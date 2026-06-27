import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import suppress
from typing import Any, Dict, Optional

import asyncpg
from aiohttp import web
from redis.asyncio import Redis

APP_NAME = os.getenv("APP_NAME", "secret-rotation-skill")
PG_DSN = os.getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.getenv("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.getenv("REDIS_CACHE_PORT", "6379"))
PORT = int(os.getenv("PORT", "8080"))

CREATE_SECRET_VERSIONS_SQL = """
CREATE TABLE IF NOT EXISTS secret_versions(
    id BIGSERIAL PRIMARY KEY,
    service_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    secret_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(service_name, version)
)
"""

logger = logging.getLogger(APP_NAME)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False


def log_event(level: int, event: str, **fields: Any) -> None:
    record: Dict[str, Any] = {
        "service": APP_NAME,
        "event": event,
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    record.update(fields)
    logger.log(level, json.dumps(record, separators=(",", ":"), default=str))


async def init_postgres(app: web.Application) -> None:
    started = time.perf_counter()
    try:
        pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4, command_timeout=10)
        async with pool.acquire() as conn:
            await conn.execute(CREATE_SECRET_VERSIONS_SQL)
        app["pg_pool"] = pool
        app["pg_ready"] = True
        log_event(logging.INFO, "dependency_ready", dependency="postgres", operation="schema_init", latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except Exception as exc:
        app["pg_pool"] = None
        app["pg_ready"] = False
        log_event(logging.WARNING, "dependency_unavailable", dependency="postgres", operation="schema_init", error=type(exc).__name__, latency_ms=round((time.perf_counter() - started) * 1000, 2))


async def init_redis(app: web.Application) -> None:
    started = time.perf_counter()
    client: Optional[Redis] = None
    try:
        client = Redis(host=REDIS_CACHE_HOST, port=REDIS_CACHE_PORT, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        await client.ping()
        app["redis"] = client
        app["redis_ready"] = True
        log_event(logging.INFO, "dependency_ready", dependency="redis-cache", operation="ping", latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except Exception as exc:
        if client is not None:
            with suppress(Exception):
                await client.aclose()
        app["redis"] = None
        app["redis_ready"] = False
        log_event(logging.WARNING, "dependency_unavailable", dependency="redis-cache", operation="ping", error=type(exc).__name__, latency_ms=round((time.perf_counter() - started) * 1000, 2))


@web.middleware
async def request_logging_middleware(request: web.Request, handler):
    started = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", hashlib.sha256(f"{time.time_ns()}:{id(request)}".encode()).hexdigest()[:16])
    status = 500
    try:
        response = await handler(request)
        status = response.status
        return response
    except web.HTTPException as exc:
        status = exc.status
        raise exc
    except Exception as exc:
        log_event(logging.ERROR, "request_failed", request_id=request_id, method=request.method, path=request.path, error=type(exc).__name__)
        raise web.HTTPInternalServerError(text=json.dumps({"status": "error"}), content_type="application/json")
    finally:
        log_event(logging.INFO, "request_complete", request_id=request_id, method=request.method, path=request.path, status=status, latency_ms=round((time.perf_counter() - started) * 1000, 2))


async def healthz(request: web.Request) -> web.Response:
    app = request.app
    body = {
        "status": "ok",
        "service": APP_NAME,
        "dependencies": {
            "postgres": "ready" if app.get("pg_ready") else "unavailable",
            "redis-cache": "ready" if app.get("redis_ready") else "unavailable",
        },
    }
    return web.json_response(body, status=200)


async def startup(app: web.Application) -> None:
    log_event(logging.INFO, "service_starting", port=PORT)
    await asyncio.gather(init_postgres(app), init_redis(app))
    log_event(logging.INFO, "service_started", port=PORT, postgres_ready=app.get("pg_ready", False), redis_ready=app.get("redis_ready", False))


async def cleanup(app: web.Application) -> None:
    log_event(logging.INFO, "service_stopping")
    pool = app.get("pg_pool")
    if pool is not None:
        await pool.close()
    redis_client = app.get("redis")
    if redis_client is not None:
        await redis_client.aclose()
    log_event(logging.INFO, "service_stopped")


def create_app() -> web.Application:
    app = web.Application(middlewares=[request_logging_middleware])
    app["pg_ready"] = False
    app["redis_ready"] = False
    app.router.add_get("/healthz", healthz)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def main() -> None:
    configure_logging()
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
