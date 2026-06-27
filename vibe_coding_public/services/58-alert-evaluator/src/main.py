import logging, os, sys, json
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("alert-evaluator")

rcache = None
rstream = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global rcache, rstream
    try:
        rcache = aioredis.Redis(
            host=os.environ.get("REDIS_CACHE_HOST","redis-cache"),
            port=int(os.environ.get("REDIS_CACHE_PORT","6379")),
            socket_connect_timeout=2, decode_responses=True)
        await rcache.ping()
        log.info("redis-cache ready")
    except Exception as e:
        log.error("alert-evaluator: redis-cache init: %s", e)
    try:
        rstream = aioredis.Redis(
            host=os.environ.get("REDIS_STREAM_HOST","redis-stream"),
            port=int(os.environ.get("REDIS_STREAM_PORT","6379")),
            socket_connect_timeout=2, decode_responses=True)
        await rstream.ping()
        log.info("redis-stream ready")
    except Exception as e:
        log.error("alert-evaluator: redis-stream init: %s", e)
    yield
    if rcache: await rcache.close()
    if rstream: await rstream.close()

app = FastAPI(lifespan=lifespan)

class RuleIn(BaseModel):
    metric: str
    threshold: float
    op: str  # gt, lt, eq

class EvalIn(BaseModel):
    device_id: str
    metric: str
    value: float

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "alert-evaluator"}

@app.get("/alerts")
async def get_alerts():
    try:
        keys = await rcache.keys("rules:*")
        rules = []
        for key in keys:
            data = await rcache.hgetall(key)
            if data: rules.append(data)
        return {"count": len(rules), "rules": rules}
    except Exception as e:
        log.error("alert-evaluator: GET /alerts: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/rules", status_code=201)
async def create_rule(r: RuleIn):
    try:
        await rcache.hset(f"rules:{r.metric}", mapping={"metric": r.metric, "threshold": str(r.threshold), "op": r.op})
        return {"metric": r.metric, "threshold": r.threshold, "op": r.op, "status": "saved"}
    except Exception as e:
        log.error("alert-evaluator: POST /rules: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/evaluate")
async def evaluate(e: EvalIn):
    try:
        rule = await rcache.hgetall(f"rules:{e.metric}")
        if not rule:
            return {"device_id": e.device_id, "metric": e.metric, "value": e.value, "alert": False, "reason": "no rule"}
        threshold = float(rule.get("threshold", 0))
        op = rule.get("op", "gt")
        triggered = False
        if op == "gt" and e.value > threshold: triggered = True
        elif op == "lt" and e.value < threshold: triggered = True
        elif op == "eq" and e.value == threshold: triggered = True
        if triggered:
            payload = {"device_id": e.device_id, "metric": e.metric, "value": e.value, "threshold": threshold, "op": op}
            try:
                await rstream.xadd("events:alerts", {"event": "alert.triggered", "payload": json.dumps(payload)})
            except Exception as se:
                log.error("alert-evaluator: stream publish: %s", se)
        return {"device_id": e.device_id, "metric": e.metric, "value": e.value, "alert": triggered, "threshold": threshold, "op": op}
    except Exception as ex:
        log.error("alert-evaluator: POST /evaluate: %s", ex)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
