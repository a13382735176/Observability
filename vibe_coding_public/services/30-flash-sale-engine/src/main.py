import logging, os, sys, time
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("flash-sale-engine")

cache: aioredis.Redis = None
stream: aioredis.Redis = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global cache, stream
    try:
        cache = aioredis.Redis(
            host=os.environ.get("REDIS_CACHE_HOST", "redis-cache"),
            port=int(os.environ.get("REDIS_CACHE_PORT", "6379")),
            socket_connect_timeout=2, decode_responses=True)
        await cache.ping()
        log.info("redis-cache connected")
    except Exception as e:
        log.error("redis-cache connect failed: %s", e)
    try:
        stream = aioredis.Redis(
            host=os.environ.get("REDIS_STREAM_HOST", "redis-stream"),
            port=int(os.environ.get("REDIS_STREAM_PORT", "6379")),
            socket_connect_timeout=2, decode_responses=True)
        await stream.ping()
        log.info("redis-stream connected")
    except Exception as e:
        log.error("redis-stream connect failed: %s", e)
    yield
    if cache: await cache.close()
    if stream: await stream.close()

app = FastAPI(lifespan=lifespan)

class SaleIn(BaseModel):
    sku: str
    discount_pct: int
    duration_s: int

class PurchaseIn(BaseModel):
    sku: str
    user_id: str

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "flash-sale-engine"}

@app.get("/sales/active")
async def get_active():
    try:
        keys = await cache.keys("flashsale:*")
        sales = []
        for k in keys:
            data = await cache.hgetall(k)
            if data:
                sales.append({"sku": k.replace("flashsale:", ""), **data})
        return sales
    except Exception as e:
        log.error("GET /sales/active failed: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/sales", status_code=201)
async def create_sale(s: SaleIn):
    key = f"flashsale:{s.sku}"
    try:
        await cache.hset(key, mapping={"discount_pct": s.discount_pct, "started_at": int(time.time())})
        await cache.expire(key, s.duration_s)
        return {"sku": s.sku, "discount_pct": s.discount_pct, "duration_s": s.duration_s}
    except Exception as e:
        log.error("POST /sales failed: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/purchase", status_code=201)
async def purchase(p: PurchaseIn):
    try:
        sale = await cache.hgetall(f"flashsale:{p.sku}")
        if not sale:
            raise HTTPException(404, "no active sale for this sku")
        await stream.xadd("flash:purchases", {"sku": p.sku, "user_id": p.user_id, "ts": str(int(time.time()))})
        return {"sku": p.sku, "user_id": p.user_id, "discount_pct": sale.get("discount_pct", "0")}
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /purchase failed: %s", e)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
