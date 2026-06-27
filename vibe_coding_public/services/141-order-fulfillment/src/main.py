import logging, os, sys
from contextlib import asynccontextmanager
from typing import List, Optional

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("order-fulfillment")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_STREAM_HOST = os.environ.get("REDIS_STREAM_HOST", "redis-stream")
REDIS_STREAM_PORT = int(os.environ.get("REDIS_STREAM_PORT", "6379"))

pool = psycopg_pool.AsyncConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, open=False,
    kwargs={"connect_timeout": 2},
)

rclient = redis.Redis(
    host=REDIS_STREAM_HOST, port=REDIS_STREAM_PORT,
    socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS orders("
                "id BIGSERIAL PRIMARY KEY,"
                "user_id TEXT NOT NULL,"
                "total_cents BIGINT NOT NULL DEFAULT 0,"
                "status TEXT NOT NULL DEFAULT 'placed',"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS order_items("
                "id BIGSERIAL PRIMARY KEY,"
                "order_id BIGINT NOT NULL,"
                "sku TEXT NOT NULL,"
                "quantity INT NOT NULL,"
                "price_cents INT NOT NULL)"
            )
            await conn.commit()
        log.info("order-fulfillment: db init ok")
    except Exception as e:
        log.error("order-fulfillment: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class OrderItemIn(BaseModel):
    sku: str
    quantity: int
    price_cents: int


class OrderIn(BaseModel):
    user_id: str
    items: List[OrderItemIn]


class StatusIn(BaseModel):
    status: str


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "order-fulfillment"}


@app.post("/orders", status_code=201)
async def create_order(body: OrderIn):
    if not body.items:
        raise HTTPException(status_code=400, detail="items required")
    total = sum(int(i.quantity) * int(i.price_cents) for i in body.items)
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO orders(user_id,total_cents) VALUES(%s,%s) "
                "RETURNING id,user_id,total_cents,status,created_at",
                (body.user_id, total),
            )).fetchone()
            order_id = row[0]
            items_out = []
            for it in body.items:
                ir = await (await conn.execute(
                    "INSERT INTO order_items(order_id,sku,quantity,price_cents) "
                    "VALUES(%s,%s,%s,%s) RETURNING id,order_id,sku,quantity,price_cents",
                    (order_id, it.sku, it.quantity, it.price_cents),
                )).fetchone()
                items_out.append({
                    "id": ir[0], "order_id": ir[1], "sku": ir[2],
                    "quantity": ir[3], "price_cents": ir[4],
                })
            await conn.commit()
    except Exception as e:
        log.error("order-fulfillment: POST /orders db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:orders", {
            "order_id": str(order_id),
            "user_id": body.user_id,
            "total_cents": str(total),
        })
    except Exception as e:
        log.error("order-fulfillment: redis xadd events:orders: %s", e)
    return {
        "id": order_id, "user_id": row[1], "total_cents": row[2],
        "status": row[3], "created_at": str(row[4]),
        "items": items_out,
    }


@app.get("/orders/user/{user_id}")
async def list_user_orders(user_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,user_id,total_cents,status,created_at "
                "FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 20",
                (user_id,),
            )).fetchall()
        return [
            {"id": r[0], "user_id": r[1], "total_cents": r[2],
             "status": r[3], "created_at": str(r[4])}
            for r in rows
        ]
    except Exception as e:
        log.error("order-fulfillment: GET /orders/user/%s: %s", user_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: int, body: StatusIn):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "UPDATE orders SET status=%s WHERE id=%s "
                "RETURNING id,user_id,total_cents,status,created_at",
                (body.status, order_id),
            )).fetchone()
            await conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error("order-fulfillment: PUT /orders/%s/status db: %s", order_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:order_status", {
            "order_id": str(row[0]),
            "status": row[3],
        })
    except Exception as e:
        log.error("order-fulfillment: redis xadd events:order_status: %s", e)
    return {
        "id": row[0], "user_id": row[1], "total_cents": row[2],
        "status": row[3], "created_at": str(row[4]),
    }


@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT o.id,o.user_id,o.total_cents,o.status,o.created_at,"
                "       i.id,i.sku,i.quantity,i.price_cents "
                "FROM orders o LEFT JOIN order_items i ON i.order_id=o.id "
                "WHERE o.id=%s ORDER BY i.id",
                (order_id,),
            )).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="not found")
        head = rows[0]
        items = []
        for r in rows:
            if r[5] is not None:
                items.append({
                    "id": r[5], "sku": r[6],
                    "quantity": r[7], "price_cents": r[8],
                })
        return {
            "id": head[0], "user_id": head[1], "total_cents": head[2],
            "status": head[3], "created_at": str(head[4]),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("order-fulfillment: GET /orders/%s: %s", order_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
