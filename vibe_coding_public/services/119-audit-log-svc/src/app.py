import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("audit-log-svc")

PG_DSN = os.getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_HOST = os.getenv("REDIS_STREAM_HOST", "redis-stream")
REDIS_PORT = int(os.getenv("REDIS_STREAM_PORT", "6379"))

rdb = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, socket_timeout=2, socket_connect_timeout=2)


def _conn():
    return psycopg.connect(PG_DSN, connect_timeout=2)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    id SERIAL PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    details JSONB DEFAULT '{}'::jsonb,
                    ts TIMESTAMPTZ DEFAULT NOW()
                )"""
            )
            c.commit()
        log.info("audit-log-svc: postgres ready")
    except Exception as e:
        log.error("audit-log-svc: db init: %s", e)
    yield


app = FastAPI(lifespan=lifespan)


class Event(BaseModel):
    actor_id: str
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any] = {}


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "audit-log-svc"}


@app.post("/events", status_code=201)
def post_event(ev: Event):
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_events(actor_id, action, resource_type, resource_id, details) "
                "VALUES(%s, %s, %s, %s, %s::jsonb) RETURNING id, ts",
                (ev.actor_id, ev.action, ev.resource_type, ev.resource_id, json.dumps(ev.details)),
            )
            row = cur.fetchone()
            c.commit()
    except Exception as e:
        log.error("audit-log-svc: insert event: %s", e)
        raise HTTPException(status_code=502, detail="db error")
    try:
        rdb.xadd(
            "events:audit",
            {
                "id": str(row[0]),
                "actor_id": ev.actor_id,
                "action": ev.action,
                "resource_type": ev.resource_type,
                "resource_id": ev.resource_id,
            },
            maxlen=10000,
            approximate=True,
        )
    except Exception as e:
        log.error("audit-log-svc: xadd: %s", e)
    return {"id": row[0], "ts": row[1].isoformat()}


@app.get("/events/{actor_id}")
def events_by_actor(actor_id: str):
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, action, resource_type, resource_id, details, ts "
                "FROM audit_events WHERE actor_id=%s ORDER BY id DESC LIMIT 50",
                (actor_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        log.error("audit-log-svc: by actor: %s", e)
        raise HTTPException(status_code=502, detail="db error")
    return [
        {"id": r[0], "action": r[1], "resource_type": r[2], "resource_id": r[3], "details": r[4], "ts": r[5].isoformat()}
        for r in rows
    ]


@app.get("/events/resource/{resource_id}")
def events_by_resource(resource_id: str):
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, actor_id, action, resource_type, details, ts "
                "FROM audit_events WHERE resource_id=%s ORDER BY id DESC LIMIT 50",
                (resource_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        log.error("audit-log-svc: by resource: %s", e)
        raise HTTPException(status_code=502, detail="db error")
    return [
        {"id": r[0], "actor_id": r[1], "action": r[2], "resource_type": r[3], "details": r[4], "ts": r[5].isoformat()}
        for r in rows
    ]
