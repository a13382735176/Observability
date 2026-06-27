import logging, os, sys
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("webhook-dispatcher")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "http://mock-upstream:8080")

pool = psycopg_pool.AsyncConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, open=False,
    kwargs={"connect_timeout": 2},
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS webhook_subscriptions("
                "id BIGSERIAL PRIMARY KEY,"
                "event_type TEXT NOT NULL,"
                "target_url TEXT NOT NULL,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS webhook_deliveries("
                "id BIGSERIAL PRIMARY KEY,"
                "subscription_id BIGINT,"
                "event_type TEXT,"
                "status_code INT,"
                "error TEXT,"
                "dispatched_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("webhook-dispatcher: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class SubscribeIn(BaseModel):
    event_type: str
    target_url: Optional[str] = None


class DispatchIn(BaseModel):
    event_type: str
    payload: Optional[dict] = None


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "webhook-dispatcher"}


@app.post("/subscriptions", status_code=201)
async def create_subscription(body: SubscribeIn):
    target = body.target_url or UPSTREAM_URL
    if not (target.startswith("http://") or target.startswith("https://")):
        target = UPSTREAM_URL
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO webhook_subscriptions(event_type,target_url) VALUES(%s,%s) "
                "RETURNING id,event_type,target_url,created_at",
                (body.event_type, target),
            )).fetchone()
            await conn.commit()
        return {"id": row[0], "event_type": row[1], "target_url": row[2], "created_at": str(row[3])}
    except Exception as e:
        log.error("webhook-dispatcher: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/subscriptions")
async def list_subscriptions(event_type: Optional[str] = None):
    try:
        async with pool.connection() as conn:
            if event_type:
                rows = await (await conn.execute(
                    "SELECT id,event_type,target_url,created_at FROM webhook_subscriptions "
                    "WHERE event_type=%s ORDER BY id DESC LIMIT 100",
                    (event_type,),
                )).fetchall()
            else:
                rows = await (await conn.execute(
                    "SELECT id,event_type,target_url,created_at FROM webhook_subscriptions "
                    "ORDER BY id DESC LIMIT 100"
                )).fetchall()
        return [
            {"id": r[0], "event_type": r[1], "target_url": r[2], "created_at": str(r[3])}
            for r in rows
        ]
    except Exception as e:
        log.error("webhook-dispatcher: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "DELETE FROM webhook_subscriptions WHERE id=%s RETURNING id",
                (sub_id,),
            )).fetchone()
            await conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {"id": row[0], "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        log.error("webhook-dispatcher: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.post("/dispatch")
async def dispatch(body: DispatchIn):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,event_type,target_url FROM webhook_subscriptions WHERE event_type=%s",
                (body.event_type,),
            )).fetchall()
    except Exception as e:
        log.error("webhook-dispatcher: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})

    if not rows:
        return {"event_type": body.event_type, "delivered": 0, "results": []}

    payload = body.payload or {}
    results = []
    async with httpx.AsyncClient(timeout=2.0) as client:
        for sub_id, event_type, target_url in rows:
            url = target_url
            if not (isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))):
                url = UPSTREAM_URL
            status_code = None
            err_text = None
            try:
                resp = await client.post(url, json={"event_type": event_type, "payload": payload})
                status_code = resp.status_code
            except Exception as e:
                err_text = str(e)
                log.error("webhook-dispatcher: %s", e)
            try:
                async with pool.connection() as conn:
                    await conn.execute(
                        "INSERT INTO webhook_deliveries(subscription_id,event_type,status_code,error) "
                        "VALUES(%s,%s,%s,%s)",
                        (sub_id, event_type, status_code, err_text),
                    )
                    await conn.commit()
            except Exception as e:
                log.error("webhook-dispatcher: %s", e)
            results.append({
                "subscription_id": sub_id, "target_url": url,
                "status_code": status_code, "error": err_text,
            })
    delivered = sum(1 for r in results if r["status_code"] and 200 <= r["status_code"] < 300)
    return {"event_type": body.event_type, "delivered": delivered, "results": results}


@app.get("/deliveries")
async def list_deliveries():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,subscription_id,event_type,status_code,error,dispatched_at "
                "FROM webhook_deliveries ORDER BY id DESC LIMIT 50"
            )).fetchall()
        return [
            {"id": r[0], "subscription_id": r[1], "event_type": r[2],
             "status_code": r[3], "error": r[4], "dispatched_at": str(r[5])}
            for r in rows
        ]
    except Exception as e:
        log.error("webhook-dispatcher: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
