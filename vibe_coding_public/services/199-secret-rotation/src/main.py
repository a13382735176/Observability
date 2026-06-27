import hashlib
import logging
import os
import sys
from contextlib import asynccontextmanager

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SERVICE = "secret-rotation"
PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(SERVICE)

pool = psycopg_pool.AsyncConnectionPool(
    PG_DSN,
    min_size=1,
    max_size=4,
    timeout=2,
    open=False,
    kwargs={"connect_timeout": 2},
)

rclient = redis.Redis(
    host=REDIS_CACHE_HOST,
    port=REDIS_CACHE_PORT,
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=True,
)


class RotateIn(BaseModel):
    service_name: str = Field(min_length=1, max_length=120)
    secret_value: str = Field(min_length=8, max_length=4096)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS secret_versions("
                "id BIGSERIAL PRIMARY KEY,"
                "service_name TEXT NOT NULL,"
                "version INTEGER NOT NULL,"
                "secret_hash TEXT NOT NULL,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "UNIQUE(service_name, version))"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS secret_versions_lookup_idx "
                "ON secret_versions(service_name, version DESC)"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("ERROR %s: db init failed: %s", SERVICE, e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


def secret_hash(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def cache_key(service_name: str) -> str:
    return f"secret:latest:{service_name}"


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE}


@app.post("/rotate")
async def rotate_secret(body: RotateIn):
    sname = body.service_name.strip()
    if not sname:
        raise HTTPException(status_code=400, detail="service_name required")

    shash = secret_hash(body.secret_value)

    try:
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM secret_versions WHERE service_name=%s",
                    (sname,),
                )
            ).fetchone()
            version = int(row[0] if row else 1)
            await conn.execute(
                "INSERT INTO secret_versions(service_name, version, secret_hash) VALUES(%s, %s, %s)",
                (sname, version, shash),
            )
            await conn.commit()
    except Exception as e:
        log.error("ERROR %s: POST /rotate db: %s", SERVICE, e)
        return JSONResponse(status_code=503, content={"error": "db error"})

    try:
        rclient.set(cache_key(sname), f"{version}:{shash}", ex=3600)
    except Exception as e:
        log.error("ERROR %s: POST /rotate cache set: %s", SERVICE, e)

    return {"service_name": sname, "version": version, "secret_hash": shash}


@app.get("/latest/{service_name}")
async def latest_secret(service_name: str):
    sname = service_name.strip()
    if not sname:
        raise HTTPException(status_code=400, detail="service_name required")

    try:
        cached = rclient.get(cache_key(sname))
        if cached:
            version_s, shash = cached.split(":", 1)
            return {
                "service_name": sname,
                "version": int(version_s),
                "secret_hash": shash,
                "source": "cache",
            }
    except Exception as e:
        log.error("ERROR %s: GET /latest/%s cache get: %s", SERVICE, sname, e)

    try:
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT version, secret_hash FROM secret_versions "
                    "WHERE service_name=%s ORDER BY version DESC LIMIT 1",
                    (sname,),
                )
            ).fetchone()
    except Exception as e:
        log.error("ERROR %s: GET /latest/%s db: %s", SERVICE, sname, e)
        return JSONResponse(status_code=503, content={"error": "db error"})

    if not row:
        raise HTTPException(status_code=404, detail="service not found")

    version, shash = int(row[0]), str(row[1])
    try:
        rclient.set(cache_key(sname), f"{version}:{shash}", ex=3600)
    except Exception as e:
        log.error("ERROR %s: GET /latest/%s cache set: %s", SERVICE, sname, e)

    return {
        "service_name": sname,
        "version": version,
        "secret_hash": shash,
        "source": "db",
    }


@app.get("/history/{service_name}")
async def list_history(service_name: str, limit: int = 20):
    sname = service_name.strip()
    if not sname:
        raise HTTPException(status_code=400, detail="service_name required")
    if limit <= 0:
        limit = 20
    if limit > 200:
        limit = 200

    try:
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT version, secret_hash, created_at "
                    "FROM secret_versions WHERE service_name=%s "
                    "ORDER BY version DESC LIMIT %s",
                    (sname, limit),
                )
            ).fetchall()
    except Exception as e:
        log.error("ERROR %s: GET /history/%s db: %s", SERVICE, sname, e)
        return JSONResponse(status_code=503, content={"error": "db error"})

    out = [
        {
            "version": int(r[0]),
            "secret_hash": str(r[1]),
            "created_at": r[2].isoformat(),
        }
        for r in rows
    ]
    return {"service_name": sname, "items": out}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
