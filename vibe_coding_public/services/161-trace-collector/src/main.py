import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("trace-collector")

SERVICE = "trace-collector"
SLOW_NS = 1_000_000_000  # 1 second

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS spans("
                "id BIGSERIAL PRIMARY KEY,"
                "trace_id TEXT NOT NULL,"
                "span_id TEXT NOT NULL,"
                "parent_span_id TEXT,"
                "service TEXT NOT NULL,"
                "operation TEXT NOT NULL,"
                "start_ns BIGINT NOT NULL,"
                "duration_ns BIGINT NOT NULL,"
                "attributes JSONB NOT NULL DEFAULT '{}'::jsonb,"
                "recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS spans_trace_id_idx ON spans(trace_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS spans_service_recorded_at_idx "
                "ON spans(service, recorded_at DESC)"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("trace-collector: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class SpanIn(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    service: str
    operation: str
    start_ns: int
    duration_ns: int
    attributes: Dict[str, Any] = Field(default_factory=dict)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": SERVICE}


@app.post("/spans", status_code=201)
async def create_span(body: SpanIn):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO spans(trace_id, span_id, parent_span_id, service, operation, "
                "start_ns, duration_ns, attributes) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
                "RETURNING id, trace_id, span_id, parent_span_id, service, operation, "
                "start_ns, duration_ns, attributes, recorded_at",
                (
                    body.trace_id, body.span_id, body.parent_span_id,
                    body.service, body.operation,
                    body.start_ns, body.duration_ns,
                    json.dumps(body.attributes or {}),
                ),
            )).fetchone()
            await conn.commit()
    except Exception as e:
        log.error("trace-collector: POST /spans db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})

    if body.duration_ns > SLOW_NS:
        try:
            rclient.xadd("events:traces", {
                "trace_id": body.trace_id,
                "service": body.service,
                "operation": body.operation,
                "duration_ns": str(body.duration_ns),
            })
        except Exception as e:
            log.error("trace-collector: redis xadd slow trace: %s", e)

    return _row_to_span(row)


@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id, trace_id, span_id, parent_span_id, service, operation, "
                "start_ns, duration_ns, attributes, recorded_at "
                "FROM spans WHERE trace_id=%s ORDER BY start_ns ASC LIMIT 1000",
                (trace_id,),
            )).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="not found")
        return [_row_to_span(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        log.error("trace-collector: GET /traces/%s db: %s", trace_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/traces/recent")
async def recent_traces():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT trace_id FROM ("
                "  SELECT trace_id, id FROM spans ORDER BY id DESC LIMIT 1000"
                ") AS s GROUP BY trace_id ORDER BY MAX(id) DESC LIMIT 50"
            )).fetchall()
        return [{"trace_id": r[0]} for r in rows]
    except Exception as e:
        log.error("trace-collector: GET /traces/recent db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/slow")
async def slow_traces():
    try:
        entries = rclient.xrevrange("events:traces", count=20)
    except Exception as e:
        log.error("trace-collector: GET /slow redis: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    out = []
    for entry_id, fields in entries:
        item = dict(fields) if fields else {}
        item["_id"] = entry_id
        out.append(item)
    return out


def _row_to_span(r):
    if r is None:
        return None
    attrs = r[8]
    if isinstance(attrs, (bytes, bytearray)):
        try:
            attrs = json.loads(attrs.decode("utf-8"))
        except Exception:
            attrs = {}
    elif isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except Exception:
            attrs = {}
    return {
        "id": r[0],
        "trace_id": r[1],
        "span_id": r[2],
        "parent_span_id": r[3],
        "service": r[4],
        "operation": r[5],
        "start_ns": r[6],
        "duration_ns": r[7],
        "attributes": attrs or {},
        "recorded_at": str(r[9]),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
