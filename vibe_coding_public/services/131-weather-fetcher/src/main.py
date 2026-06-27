import json
import logging
import os
import sys

import httpx
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("weather-fetcher")

REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://mock-upstream:8080")

app = FastAPI()

rclient = aioredis.from_url(
    f"redis://{REDIS_CACHE_HOST}:{REDIS_CACHE_PORT}",
    socket_connect_timeout=2,
    socket_timeout=2,
    decode_responses=True,
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "weather-fetcher"}


@app.get("/weather/{city}")
async def get_weather(city: str):
    key = f"wx:{city}"
    try:
        cached = await rclient.get(key)
    except Exception as e:
        log.error("weather-fetcher: cache get %s: %s", key, e)
        cached = None

    if cached:
        try:
            data = json.loads(cached)
        except Exception:
            data = {"raw": cached}
        return {"city": city, "source": "cache", "data": data}

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{UPSTREAM_URL}/weather", params={"city": city})
            if resp.status_code >= 500:
                log.error("weather-fetcher: upstream %s status %d", city, resp.status_code)
                raise HTTPException(status_code=502, detail="upstream error")
            payload = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        log.error("weather-fetcher: upstream %s: %s", city, e)
        raise HTTPException(status_code=502, detail="upstream error")

    try:
        await rclient.setex(key, 300, json.dumps(payload))
    except Exception as e:
        log.error("weather-fetcher: cache setex %s: %s", key, e)

    return {"city": city, "source": "upstream", "data": payload}


@app.get("/cached")
async def list_cached():
    try:
        keys = await rclient.keys("wx:*")
    except Exception as e:
        log.error("weather-fetcher: cache keys: %s", e)
        raise HTTPException(status_code=502, detail="cache error")
    cities = [k[len("wx:"):] for k in keys]
    return {"cities": sorted(cities)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
