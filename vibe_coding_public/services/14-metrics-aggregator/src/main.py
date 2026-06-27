"""
14-metrics-aggregator — consume metric events, expose counters.

Consumes from Redis Stream `metrics:queue` (each event is a flat dict
with at least `metric` and `value`). For each event, INCRBY the counter
key `counter:<metric>` in redis-cache by value. Self-produces test events
every 1s.

Endpoints:
    GET /healthz
    GET /metrics       — Prometheus-ish text dump of all counter:* keys
"""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("metrics-aggregator")

CACHE_URL = os.environ.get("REDIS_CACHE_URL", "redis://redis-cache:6379/0")
STREAM_URL = os.environ.get("REDIS_STREAM_URL", "redis://redis-stream:6379/0")
STREAM_KEY = "metrics:queue"
GROUP = "aggregators"
CONSUMER = "a1"

SHUTDOWN = asyncio.Event()
STATS = {"consumed": 0, "errors": 0}


async def producer_loop(rs: redis.Redis):
    metrics = ["http.requests", "db.queries", "cache.hits", "cache.misses"]
    i = 0
    while not SHUTDOWN.is_set():
        m = metrics[i % len(metrics)]
        try:
            await rs.xadd(STREAM_KEY, {"metric": m, "value": "1"})
        except Exception as e:
            log.error("xadd error: %r", e)
        i += 1
        await asyncio.sleep(1)


async def consumer_loop(rs: redis.Redis, rc: redis.Redis):
    try:
        await rs.xgroup_create(STREAM_KEY, GROUP, id="$", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            log.error("xgroup_create error: %r", e)
    while not SHUTDOWN.is_set():
        try:
            res = await rs.xreadgroup(
                groupname=GROUP, consumername=CONSUMER,
                streams={STREAM_KEY: ">"}, count=20, block=1000,
            )
        except Exception as e:
            STATS["errors"] += 1
            log.error("xreadgroup error: %r", e)
            await asyncio.sleep(1)
            continue
        if not res:
            continue
        for _stream, msgs in res:
            for msg_id, fields in msgs:
                try:
                    metric = fields.get("metric", "unknown")
                    value = int(fields.get("value", "1"))
                    await rc.incrby(f"counter:{metric}", value)
                    await rs.xack(STREAM_KEY, GROUP, msg_id)
                    STATS["consumed"] += 1
                except redis.RedisError as e:
                    STATS["errors"] += 1
                    log.error("incrby/xack failed: %r", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    rc = redis.from_url(CACHE_URL, decode_responses=True,
                        socket_timeout=2.0, socket_connect_timeout=2.0)
    rs = redis.from_url(STREAM_URL, decode_responses=True,
                        socket_timeout=2.0, socket_connect_timeout=2.0)
    t1 = asyncio.create_task(consumer_loop(rs, rc))
    t2 = asyncio.create_task(producer_loop(rs))
    log.info("metrics-aggregator started")
    yield
    SHUTDOWN.set()
    t1.cancel(); t2.cancel()
    for t in (t1, t2):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    await rc.aclose(); await rs.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/metrics")
async def metrics():
    rc = redis.from_url(CACHE_URL, decode_responses=True,
                        socket_timeout=2.0, socket_connect_timeout=2.0)
    out_lines = [f"# stats {STATS}"]
    try:
        keys = await rc.keys("counter:*")
        for k in keys:
            v = await rc.get(k)
            out_lines.append(f"{k} {v}")
    finally:
        await rc.aclose()
    return "\n".join(out_lines)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_config=None)
