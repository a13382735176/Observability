import logging
import os

import redis
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("uvicorn.error")

CACHE_HOST = os.getenv("REDIS_CACHE_HOST", "redis-cache")
STREAM_HOST = os.getenv("REDIS_STREAM_HOST", "redis-stream")

cache = redis.Redis(
    host=CACHE_HOST, port=6379,
    socket_connect_timeout=2, socket_timeout=2,
    decode_responses=True
)
stream = redis.Redis(
    host=STREAM_HOST, port=6379,
    socket_connect_timeout=2, socket_timeout=2,
    decode_responses=True
)

app = FastAPI()


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "vitals-monitor"}


@app.post("/vitals", status_code=201)
async def post_vitals(body: dict):
    patient_id = body.get("patient_id", "")
    try:
        vitals = {
            "heart_rate": str(body.get("heart_rate", "")),
            "bp": str(body.get("bp", "")),
            "spo2": str(body.get("spo2", "")),
            "temp_c": str(body.get("temp_c", "")),
        }
        cache.hset(f"vitals:{patient_id}", mapping=vitals)
        stream.xadd("events:vitals", {"patient_id": patient_id, **vitals})
        return {"ok": True, "patient_id": patient_id, **vitals}
    except Exception as e:
        log.error("vitals-monitor: %s", e)
        return JSONResponse(status_code=503, content={"error": "error"})


@app.get("/vitals/{patient_id}/latest")
async def get_vitals(patient_id: str):
    try:
        data = cache.hgetall(f"vitals:{patient_id}")
        if not data:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"patient_id": patient_id, **data}
    except Exception as e:
        log.error("vitals-monitor: %s", e)
        return JSONResponse(status_code=503, content={"error": "error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
