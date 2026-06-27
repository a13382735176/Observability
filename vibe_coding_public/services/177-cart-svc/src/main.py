import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import redis
from fastapi import FastAPI, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cart-svc")

SERVICE = "cart-svc"
PG_DSN = os.environ.get("PG_DSN", "host=postgres port=5432 user=vibe password=vibe dbname=vibe")
REDIS_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))

pool: ConnectionPool | None = None
rdb: redis.Redis | None = None


def init_db():
    assert pool is not None
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    total_cents BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_lines (
                    id BIGSERIAL PRIMARY KEY,
                    order_id BIGINT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INT NOT NULL,
                    price_cents INT NOT NULL
                )
            """)
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool, rdb
    pool = ConnectionPool(
        PG_DSN,
        min_size=1,
        max_size=4,
        timeout=2,
        open=False,
        kwargs={"connect_timeout": 2},
    )
    pool.open()
    rdb = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    try:
        init_db()
    except Exception as e:
        log.error("cart-svc: init_db: %s", e)
    yield
    try:
        pool.close()
    except Exception as e:
        log.error("cart-svc: pool close: %s", e)


app = FastAPI(lifespan=lifespan)


class CartItem(BaseModel):
    sku: str
    quantity: int = 1
    price_cents: int = 0


def cart_key(user_id: str) -> str:
    return f"cart:{user_id}"


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE}


@app.post("/cart/{user_id}/items")
def add_item(user_id: str, item: CartItem):
    try:
        assert rdb is not None
        key = cart_key(user_id)
        rdb.hset(key, item.sku, json.dumps(item.model_dump()))
        rdb.expire(key, 86400)
        return {"ok": True, "user_id": user_id, "sku": item.sku}
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="cache error")


@app.get("/cart/{user_id}")
def get_cart(user_id: str):
    try:
        assert rdb is not None
        items_raw: Dict[str, str] = rdb.hgetall(cart_key(user_id)) or {}
        items: List[Dict[str, Any]] = []
        total = 0
        for sku, raw in items_raw.items():
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            qty = int(obj.get("quantity", 0))
            price = int(obj.get("price_cents", 0))
            total += qty * price
            items.append({"sku": sku, "quantity": qty, "price_cents": price})
        return {"user_id": user_id, "items": items, "total_cents": total}
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="cache error")


@app.delete("/cart/{user_id}/items/{sku}")
def remove_item(user_id: str, sku: str):
    try:
        assert rdb is not None
        removed = rdb.hdel(cart_key(user_id), sku)
        return {"ok": True, "removed": int(removed)}
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="cache error")


@app.delete("/cart/{user_id}")
def clear_cart(user_id: str):
    try:
        assert rdb is not None
        rdb.delete(cart_key(user_id))
        return {"ok": True}
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="cache error")


@app.post("/cart/{user_id}/checkout")
def checkout(user_id: str):
    try:
        assert rdb is not None
        items_raw: Dict[str, str] = rdb.hgetall(cart_key(user_id)) or {}
        if not items_raw:
            raise HTTPException(status_code=400, detail="cart empty")
        lines = []
        total = 0
        for sku, raw in items_raw.items():
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            qty = int(obj.get("quantity", 0))
            price = int(obj.get("price_cents", 0))
            total += qty * price
            lines.append((sku, qty, price))
    except HTTPException:
        raise
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="cache error")

    try:
        assert pool is not None
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO orders(user_id, total_cents) VALUES (%s, %s) RETURNING id",
                    (user_id, total),
                )
                row = cur.fetchone()
                order_id = row[0] if row else None
                for sku, qty, price in lines:
                    cur.execute(
                        "INSERT INTO order_lines(order_id, sku, quantity, price_cents) VALUES (%s, %s, %s, %s)",
                        (order_id, sku, qty, price),
                    )
            conn.commit()
    except Exception as e:
        log.error("cart-svc: %s", e)
        raise HTTPException(status_code=503, detail="db error")

    try:
        assert rdb is not None
        rdb.delete(cart_key(user_id))
    except Exception as e:
        log.error("cart-svc: %s", e)

    return {"order_id": order_id, "user_id": user_id, "total_cents": total, "lines": len(lines)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
