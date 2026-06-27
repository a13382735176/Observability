import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

SERVICE = os.environ.get("APP_NAME", "generic-service")
PG_DSN = os.environ.get("PG_DSN")
REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST")
REDIS_STREAM_HOST = os.environ.get("REDIS_STREAM_HOST")
UPSTREAM_URL = os.environ.get("UPSTREAM_URL")


def parse_port(value: str | None, default: int) -> int:
    if not value:
        return default
    if value.startswith("tcp://"):
        value = value.rsplit(":", 1)[-1]
    try:
        return int(value)
    except Exception:
        return default


REDIS_CACHE_PORT = parse_port(os.environ.get("REDIS_CACHE_PORT"), 6379)
REDIS_STREAM_PORT = parse_port(os.environ.get("REDIS_STREAM_PORT"), 6379)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(SERVICE)

pool = None
cache = None
stream = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global pool, cache, stream
    if PG_DSN:
        try:
            pool = psycopg_pool.AsyncConnectionPool(
                PG_DSN,
                min_size=1,
                max_size=4,
                timeout=2,
                open=False,
                kwargs={"connect_timeout": 2},
            )
            await pool.open(wait=True, timeout=2)
            async with pool.connection() as conn:
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS service_probe("
                    "id BIGSERIAL PRIMARY KEY,"
                    "service_name TEXT NOT NULL,"
                    "probe_kind TEXT NOT NULL,"
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
                await conn.commit()
            log.info("db init ok")
        except Exception as e:
            log.error("ERROR %s: db init failed: %s", SERVICE, e)

    if REDIS_CACHE_HOST:
        try:
            cache = redis.Redis(
                host=REDIS_CACHE_HOST,
                port=REDIS_CACHE_PORT,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            cache.ping()
            log.info("cache init ok")
        except Exception as e:
            log.error("ERROR %s: cache init failed: %s", SERVICE, e)

    if REDIS_STREAM_HOST:
        try:
            stream = redis.Redis(
                host=REDIS_STREAM_HOST,
                port=REDIS_STREAM_PORT,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            stream.ping()
            log.info("stream init ok")
        except Exception as e:
            log.error("ERROR %s: stream init failed: %s", SERVICE, e)

    yield

    if pool is not None:
        try:
            await pool.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE}


@app.post("/probe")
async def probe_deps():
    out = {
        "service": SERVICE,
        "postgres": None,
        "redis_cache": None,
        "redis_stream": None,
        "upstream": None,
    }

    if pool is not None:
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO service_probe(service_name, probe_kind) VALUES(%s, %s)",
                    (SERVICE, "manual"),
                )
                await conn.commit()
            out["postgres"] = "ok"
        except Exception as e:
            log.error("ERROR %s: probe postgres: %s", SERVICE, e)
            out["postgres"] = "error"

    if cache is not None:
        try:
            cache.set(f"probe:{SERVICE}", "ok", ex=60)
            _ = cache.get(f"probe:{SERVICE}")
            out["redis_cache"] = "ok"
        except Exception as e:
            log.error("ERROR %s: probe cache: %s", SERVICE, e)
            out["redis_cache"] = "error"

    if stream is not None:
        try:
            stream.xadd("events:probe", {"service": SERVICE, "status": "ok"})
            out["redis_stream"] = "ok"
        except Exception as e:
            log.error("ERROR %s: probe stream: %s", SERVICE, e)
            out["redis_stream"] = "error"

    if UPSTREAM_URL:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(UPSTREAM_URL)
                out["upstream"] = f"http_{r.status_code}"
        except Exception as e:
            log.error("ERROR %s: probe upstream: %s", SERVICE, e)
            out["upstream"] = "error"

    if any(v == "error" for v in out.values() if isinstance(v, str)):
        return JSONResponse(status_code=502, content=out)
    return out


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
