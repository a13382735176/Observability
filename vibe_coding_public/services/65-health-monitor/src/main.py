import logging, os, sys, json
import asyncpg, redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("health-monitor")

pool = None
rcache = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, rcache
    dsn = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
    cache_host = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
    try:
        pool = await asyncpg.create_pool(dsn, command_timeout=2, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats(
                    id serial PRIMARY KEY,
                    device_id text,
                    cpu_pct real,
                    mem_pct real,
                    ts timestamptz DEFAULT now()
                )
            """)
        log.info("health-monitor: postgres ready")
    except Exception as e:
        log.error(f"health-monitor: pg init: {e}")
    try:
        rcache = aioredis.Redis(host=cache_host, port=6379, socket_connect_timeout=2, socket_timeout=2)
        log.info("health-monitor: redis ready")
    except Exception as e:
        log.error(f"health-monitor: redis init: {e}")
    yield
    if pool: await pool.close()
    if rcache: await rcache.aclose()

app = FastAPI(lifespan=lifespan)

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "health-monitor"}

class Heartbeat(BaseModel):
    device_id: str
    cpu_pct: float
    mem_pct: float

@app.post("/heartbeat", status_code=201)
async def heartbeat(hb: Heartbeat):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO heartbeats(device_id,cpu_pct,mem_pct) VALUES($1,$2,$3)",
                hb.device_id, hb.cpu_pct, hb.mem_pct
            )
    except Exception as e:
        log.error(f"health-monitor: pg: {e}")
        raise HTTPException(503, "db error")
    try:
        ts = datetime.now(timezone.utc).isoformat()
        await rcache.hset(f"hb:{hb.device_id}", mapping={"ts": ts, "cpu": str(hb.cpu_pct), "mem": str(hb.mem_pct)})
    except Exception as e:
        log.error(f"health-monitor: redis: {e}")
    return {"ok": True}

@app.get("/unhealthy")
async def unhealthy():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT device_id FROM heartbeats
                   WHERE device_id NOT IN (
                       SELECT device_id FROM heartbeats WHERE ts > $1
                   )""", cutoff
            )
        return {"unhealthy": [r["device_id"] for r in rows]}
    except Exception as e:
        log.error(f"health-monitor: pg: {e}")
        raise HTTPException(503, "db error")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
