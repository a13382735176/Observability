"""
10-search-indexer — periodic batch indexer.

Every INDEX_INTERVAL_S, reads all rows from Postgres `products` table and
writes each as a JSON blob into Redis under key `idx:product:<id>`. Lookup
endpoint reads from Redis.

Endpoints:
    GET /healthz
    GET /index/{sku}     — return cached JSON or 404
    GET /stats           — last index time + row count
"""
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

import psycopg
import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI, HTTPException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("search-indexer")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
CACHE_URL = os.environ.get("REDIS_CACHE_URL", "redis://redis-cache:6379/0")
INTERVAL_S = float(os.environ.get("INDEX_INTERVAL_S", "10"))

STATS = {"last_index_ts": 0.0, "last_index_rows": 0, "errors": 0}
SHUTDOWN = asyncio.Event()


async def indexer_loop(r: redis.Redis):
    while not SHUTDOWN.is_set():
        start = time.time()
        try:
            with psycopg.connect(PG_DSN, connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS products ("
                        "id SERIAL PRIMARY KEY, name TEXT, price_cents INT, stock_qty INT)"
                    )
                    cur.execute("SELECT id,name,price_cents,stock_qty FROM products")
                    rows = cur.fetchall()
            for pid, name, price, qty in rows:
                blob = json.dumps({"id": pid, "name": name,
                                   "price_cents": price, "stock_qty": qty})
                await r.set(f"idx:product:{pid}", blob, ex=300)
            STATS["last_index_ts"] = start
            STATS["last_index_rows"] = len(rows)
            log.info("indexed %d rows in %.3fs", len(rows), time.time() - start)
        except psycopg.Error as e:
            STATS["errors"] += 1
            log.error("postgres error during index: %r", e)
        except redis.RedisError as e:
            STATS["errors"] += 1
            log.error("redis error during index: %r", e)
        except Exception as e:
            STATS["errors"] += 1
            log.error("unexpected error during index: %r", e)
        try:
            await asyncio.wait_for(SHUTDOWN.wait(), timeout=INTERVAL_S)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    r = redis.from_url(CACHE_URL, decode_responses=True,
                       socket_timeout=2.0, socket_connect_timeout=2.0)
    task = asyncio.create_task(indexer_loop(r))
    log.info("indexer started, interval=%ss", INTERVAL_S)
    yield
    SHUTDOWN.set()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await r.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/stats")
async def stats():
    return STATS


@app.get("/index/{pid}")
async def index_lookup(pid: int):
    r = redis.from_url(CACHE_URL, decode_responses=True,
                       socket_timeout=2.0, socket_connect_timeout=2.0)
    try:
        v = await r.get(f"idx:product:{pid}")
    finally:
        await r.aclose()
    if v is None:
        raise HTTPException(404, "not indexed")
    return json.loads(v)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_config=None)
