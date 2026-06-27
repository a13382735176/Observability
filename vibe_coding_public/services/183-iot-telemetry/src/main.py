import logging, os, sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("iot-telemetry")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_STREAM_HOST = os.environ.get("REDIS_STREAM_HOST", "redis-stream")
REDIS_STREAM_PORT = int(os.environ.get("REDIS_STREAM_PORT", "6379"))

pool = psycopg_pool.AsyncConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, open=False,
    kwargs={"connect_timeout": 2},
)

rclient = redis.Redis(
    host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT,
    socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
)


def _anomaly(value: float) -> bool:
    return value > 100 or value < 0


def _emit_event(device_id: str, sensor_type: str, value: float) -> None:
    try:
        rclient.xadd("events:sensors", {
            "device_id": device_id,
            "sensor_type": sensor_type,
            "value": str(value),
        })
    except Exception as e:
        log.error("iot-telemetry: xadd events:sensors: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS sensor_readings("
                "id BIGSERIAL PRIMARY KEY,"
                "device_id TEXT NOT NULL,"
                "sensor_type TEXT NOT NULL,"
                "value DOUBLE PRECISION NOT NULL,"
                "ts TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_ts "
                "ON sensor_readings (device_id, ts DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sensor_readings_sensor_ts "
                "ON sensor_readings (sensor_type, ts DESC)"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("iot-telemetry: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class ReadingIn(BaseModel):
    device_id: str
    sensor_type: str
    value: float
    ts_epoch_ms: Optional[int] = None


class BatchIn(BaseModel):
    readings: List[ReadingIn]


def _ts_from_epoch_ms(ms: Optional[int]):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "iot-telemetry"}


@app.post("/readings", status_code=201)
async def add_reading(body: ReadingIn):
    ts = _ts_from_epoch_ms(body.ts_epoch_ms)
    try:
        async with pool.connection() as conn:
            if ts is not None:
                row = await (await conn.execute(
                    "INSERT INTO sensor_readings(device_id,sensor_type,value,ts) "
                    "VALUES(%s,%s,%s,%s) RETURNING id, device_id, sensor_type, value, ts",
                    (body.device_id, body.sensor_type, body.value, ts),
                )).fetchone()
            else:
                row = await (await conn.execute(
                    "INSERT INTO sensor_readings(device_id,sensor_type,value) "
                    "VALUES(%s,%s,%s) RETURNING id, device_id, sensor_type, value, ts",
                    (body.device_id, body.sensor_type, body.value),
                )).fetchone()
            await conn.commit()
    except Exception as e:
        log.error("iot-telemetry: POST /readings db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})

    if _anomaly(body.value):
        _emit_event(body.device_id, body.sensor_type, body.value)

    return {
        "id": row[0], "device_id": row[1], "sensor_type": row[2],
        "value": row[3], "ts": str(row[4]),
        "anomaly": _anomaly(body.value),
    }


@app.get("/readings/{device_id}")
async def list_readings(device_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id, device_id, sensor_type, value, ts FROM sensor_readings "
                "WHERE device_id=%s ORDER BY id DESC LIMIT 100",
                (device_id,),
            )).fetchall()
        return [
            {"id": r[0], "device_id": r[1], "sensor_type": r[2],
             "value": r[3], "ts": str(r[4])}
            for r in rows
        ]
    except Exception as e:
        log.error("iot-telemetry: GET /readings/%s: %s", device_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/readings/{device_id}/avg")
async def avg_readings(device_id: str, since_minutes: int = 60):
    if since_minutes <= 0:
        since_minutes = 60
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT sensor_type, AVG(value) FROM sensor_readings "
                "WHERE device_id=%s AND ts > now() - (%s::text || ' minutes')::interval "
                "GROUP BY sensor_type",
                (device_id, str(since_minutes)),
            )).fetchall()
        return {
            "device_id": device_id,
            "since_minutes": since_minutes,
            "avg": [{"sensor_type": r[0], "avg": float(r[1]) if r[1] is not None else 0.0}
                    for r in rows],
        }
    except Exception as e:
        log.error("iot-telemetry: GET /readings/%s/avg: %s", device_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.post("/readings/batch", status_code=201)
async def add_batch(body: BatchIn):
    if not body.readings:
        raise HTTPException(status_code=400, detail="empty batch")
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO sensor_readings(device_id,sensor_type,value) "
                    "VALUES(%s,%s,%s)",
                    [(r.device_id, r.sensor_type, r.value) for r in body.readings],
                )
            await conn.commit()
    except Exception as e:
        log.error("iot-telemetry: POST /readings/batch db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})

    emitted = 0
    for r in body.readings:
        if _anomaly(r.value):
            _emit_event(r.device_id, r.sensor_type, r.value)
            emitted += 1

    return {"inserted": len(body.readings), "anomalies_emitted": emitted}


@app.get("/devices")
async def list_devices():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT DISTINCT device_id FROM sensor_readings LIMIT 100"
            )).fetchall()
        return [{"device_id": r[0]} for r in rows]
    except Exception as e:
        log.error("iot-telemetry: GET /devices: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
