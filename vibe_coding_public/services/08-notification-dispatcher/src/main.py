"""
08-notification-dispatcher — async notification consumer.

Consumes from Redis Stream `notifications:queue` and forwards each event
to UPSTREAM_URL/send. Mock upstream (nginx) returns 200, chaos can make
it 503 or slow.

HTTP endpoints:
    GET /healthz
    GET /stats        — number of dispatched + failed
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("notification-dispatcher")

STREAM_URL = os.environ.get("REDIS_STREAM_URL", "redis://redis-stream:6379/0")
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://mock-upstream:8080")
STREAM_KEY = "notifications:queue"
GROUP = "dispatchers"
CONSUMER = "c1"

STATS = {"dispatched": 0, "failed": 0}
SHUTDOWN = asyncio.Event()


async def producer_loop(r: redis.Redis):
    """Self-produce a notification every 2s so the consumer always has work."""
    i = 0
    while not SHUTDOWN.is_set():
        try:
            await r.xadd(STREAM_KEY, {"to": f"user{i}@example.com",
                                      "subject": f"hello {i}",
                                      "body": "test notification"})
        except Exception as e:
            log.error("producer xadd failed: %r", e)
        i += 1
        await asyncio.sleep(2)


async def consumer_loop(r: redis.Redis, http: httpx.AsyncClient):
    try:
        await r.xgroup_create(STREAM_KEY, GROUP, id="$", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            log.error("xgroup_create error: %r", e)
    while not SHUTDOWN.is_set():
        try:
            res = await r.xreadgroup(
                groupname=GROUP, consumername=CONSUMER,
                streams={STREAM_KEY: ">"}, count=10, block=1000,
            )
        except Exception as e:
            log.error("xreadgroup failed: %r", e)
            await asyncio.sleep(1)
            continue
        if not res:
            continue
        for _stream, msgs in res:
            for msg_id, fields in msgs:
                try:
                    resp = await http.post(f"{UPSTREAM_URL}/send",
                                           json={k: v for k, v in fields.items()})
                    if resp.status_code >= 500:
                        STATS["failed"] += 1
                        log.error("upstream 5xx: status=%d body=%r",
                                  resp.status_code, resp.text[:100])
                    else:
                        STATS["dispatched"] += 1
                        await r.xack(STREAM_KEY, GROUP, msg_id)
                except httpx.TimeoutException as e:
                    STATS["failed"] += 1
                    log.error("upstream timeout: %r", e)
                except Exception as e:
                    STATS["failed"] += 1
                    log.error("upstream error: %r", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    r = redis.from_url(STREAM_URL, decode_responses=True,
                       socket_timeout=2.0, socket_connect_timeout=2.0)
    http = httpx.AsyncClient(timeout=httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0))
    log.info("starting consumer + producer loops")
    t1 = asyncio.create_task(consumer_loop(r, http))
    t2 = asyncio.create_task(producer_loop(r))
    yield
    SHUTDOWN.set()
    t1.cancel(); t2.cancel()
    for t in (t1, t2):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    await http.aclose()
    await r.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/stats")
async def stats():
    return STATS


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_config=None)
