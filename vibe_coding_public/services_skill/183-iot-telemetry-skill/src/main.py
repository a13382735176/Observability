import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

import asyncpg
import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

APP_NAME = os.getenv("APP_NAME", "iot-telemetry-skill")
PG_DSN = os.getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_HOST = os.getenv("REDIS_STREAM_HOST", "redis-stream")
REDIS_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))
REDIS_STREAM = "events:sensors"
SERVICE_NAME = "iot-telemetry"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(APP_NAME)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sensor_readings(
  id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL,
  sensor_type TEXT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _safe_dsn(dsn: str) -> str:
    try:
        parsed = urlparse(dsn)
        if parsed.password:
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc += f":{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:***@{netloc}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return "postgres://***"


def log_event(level: int, event: str, **fields):
    payload = {"service": APP_NAME, "event": event, **fields}
    logger.log(level, json.dumps(payload, separators=(",", ":"), default=str))


def epoch_ms_to_dt(ts_epoch_ms: Optional[int]) -> datetime:
    if ts_epoch_ms is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(ts_epoch_ms / 1000, tz=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid ts_epoch_ms")


def is_anomaly(value: float) -> bool:
    return value > 100 or value < 0


class ReadingIn(BaseModel):
    device_id: str = Field(..., min_length=1)
    sensor_type: str = Field(..., min_length=1)
    value: float
    ts_epoch_ms: Optional[int] = None


class BatchIn(BaseModel):
    readings: List[ReadingIn]


class AppState:
    pg_pool: Optional[asyncpg.Pool] = None
    redis_client: Optional[redis.Redis] = None


state = AppState()


async def init_db():
    last_error = None
    for attempt in range(1, 6):
        started = time.perf_counter()
        try:
            state.pg_pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=10)
            async with state.pg_pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            log_event(logging.INFO, "postgres_ready", attempt=attempt, latency_ms=round((time.perf_counter() - started) * 1000, 2))
            return
        except Exception as exc:
            last_error = exc
            log_event(logging.WARNING, "postgres_connect_failed", attempt=attempt, latency_ms=round((time.perf_counter() - started) * 1000, 2), error=type(exc).__name__, dsn=_safe_dsn(PG_DSN))
            await asyncio.sleep(min(attempt, 3))
    raise RuntimeError(f"could not initialize postgres: {last_error}")


async def init_redis():
    state.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    started = time.perf_counter()
    try:
        await state.redis_client.ping()
        log_event(logging.INFO, "redis_ready", host=REDIS_HOST, port=REDIS_PORT, latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except Exception as exc:
        # Keep the service available for reads/writes even if anomaly publishing is temporarily degraded.
        log_event(logging.WARNING, "redis_unavailable", host=REDIS_HOST, port=REDIS_PORT, latency_ms=round((time.perf_counter() - started) * 1000, 2), error=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(logging.INFO, "startup_begin")
    await init_db()
    await init_redis()
    log_event(logging.INFO, "startup_complete")
    try:
        yield
    finally:
        log_event(logging.INFO, "shutdown_begin")
        if state.redis_client is not None:
            await state.redis_client.aclose()
        if state.pg_pool is not None:
            await state.pg_pool.close()
        log_event(logging.INFO, "shutdown_complete")


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log_event(
            logging.INFO if status < 500 else logging.ERROR,
            "request_complete",
            method=request.method,
            path=request.url.path,
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


async def publish_anomaly(reading: ReadingIn, ts: datetime):
    if not is_anomaly(reading.value) or state.redis_client is None:
        return False
    fields = {
        "device_id": reading.device_id,
        "sensor_type": reading.sensor_type,
        "value": str(reading.value),
        "ts": ts.isoformat(),
    }
    started = time.perf_counter()
    try:
        await state.redis_client.xadd(REDIS_STREAM, fields)
        log_event(logging.INFO, "anomaly_published", stream=REDIS_STREAM, sensor_type=reading.sensor_type, latency_ms=round((time.perf_counter() - started) * 1000, 2))
        return True
    except Exception as exc:
        log_event(logging.ERROR, "anomaly_publish_failed", stream=REDIS_STREAM, sensor_type=reading.sensor_type, latency_ms=round((time.perf_counter() - started) * 1000, 2), error=type(exc).__name__)
        return False


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/readings")
async def create_reading(reading: ReadingIn):
    ts = epoch_ms_to_dt(reading.ts_epoch_ms)
    started = time.perf_counter()
    try:
        async with state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO sensor_readings(device_id, sensor_type, value, ts) VALUES($1,$2,$3,$4) RETURNING id, device_id, sensor_type, value, ts",
                reading.device_id,
                reading.sensor_type,
                reading.value,
                ts,
            )
    except Exception as exc:
        log_event(logging.ERROR, "reading_insert_failed", error=type(exc).__name__, latency_ms=round((time.perf_counter() - started) * 1000, 2))
        raise HTTPException(status_code=500, detail="database insert failed")
    published = await publish_anomaly(reading, ts)
    log_event(logging.INFO, "reading_inserted", sensor_type=reading.sensor_type, anomaly=is_anomaly(reading.value), anomaly_published=published, latency_ms=round((time.perf_counter() - started) * 1000, 2))
    return {"id": row["id"], "device_id": row["device_id"], "sensor_type": row["sensor_type"], "value": row["value"], "ts": row["ts"].isoformat()}


@app.get("/readings/{device_id}")
async def get_readings(device_id: str):
    try:
        async with state.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, device_id, sensor_type, value, ts FROM sensor_readings WHERE device_id=$1 ORDER BY ts DESC, id DESC LIMIT 100",
                device_id,
            )
    except Exception as exc:
        log_event(logging.ERROR, "readings_query_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="database query failed")
    return [dict(id=r["id"], device_id=r["device_id"], sensor_type=r["sensor_type"], value=r["value"], ts=r["ts"].isoformat()) for r in rows]


@app.get("/readings/{device_id}/avg")
async def get_average(device_id: str, since_minutes: int = 60):
    if since_minutes < 0:
        raise HTTPException(status_code=400, detail="since_minutes must be non-negative")
    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    try:
        async with state.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT sensor_type, AVG(value) AS avg_value FROM sensor_readings WHERE device_id=$1 AND ts >= $2 GROUP BY sensor_type ORDER BY sensor_type",
                device_id,
                since,
            )
    except Exception as exc:
        log_event(logging.ERROR, "average_query_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="database query failed")
    return [{"sensor_type": r["sensor_type"], "avg_value": float(r["avg_value"])} for r in rows]


@app.post("/readings/batch")
async def create_batch(batch: BatchIn):
    prepared = [(r.device_id, r.sensor_type, r.value, epoch_ms_to_dt(r.ts_epoch_ms), r) for r in batch.readings]
    started = time.perf_counter()
    try:
        async with state.pg_pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "INSERT INTO sensor_readings(device_id, sensor_type, value, ts) VALUES($1,$2,$3,$4)",
                    [(d, s, v, ts) for d, s, v, ts, _ in prepared],
                )
    except Exception as exc:
        log_event(logging.ERROR, "batch_insert_failed", count=len(prepared), error=type(exc).__name__, latency_ms=round((time.perf_counter() - started) * 1000, 2))
        raise HTTPException(status_code=500, detail="database insert failed")

    anomalies = 0
    published = 0
    for _, _, value, ts, reading in prepared:
        if is_anomaly(value):
            anomalies += 1
            if await publish_anomaly(reading, ts):
                published += 1
    log_event(logging.INFO, "batch_inserted", count=len(prepared), anomalies=anomalies, anomaly_published=published, latency_ms=round((time.perf_counter() - started) * 1000, 2))
    return {"inserted": len(prepared), "anomalies": anomalies}


@app.get("/devices")
async def get_devices():
    try:
        async with state.pg_pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT device_id FROM sensor_readings ORDER BY device_id LIMIT 100")
    except Exception as exc:
        log_event(logging.ERROR, "devices_query_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="database query failed")
    return {"devices": [r["device_id"] for r in rows]}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_config=None)
