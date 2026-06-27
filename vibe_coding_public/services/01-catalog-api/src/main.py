"""
01-catalog-api — product catalog read-mostly HTTP API.

Endpoints:
    GET /healthz
    GET /products
    GET /products/{id}
    POST /products {name, price_cents, stock_qty}
Backend: Postgres (DSN in PG_DSN).
"""
import logging
import os
import sys
from contextlib import asynccontextmanager

import psycopg
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("catalog-api")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
PG_TIMEOUT_S = float(os.environ.get("PG_TIMEOUT_S", "2.0"))

POOL: psycopg_pool.AsyncConnectionPool | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global POOL
    log.info("connecting to postgres: %s", PG_DSN)
    POOL = psycopg_pool.AsyncConnectionPool(
        conninfo=PG_DSN, min_size=1, max_size=4,
        kwargs={"connect_timeout": int(PG_TIMEOUT_S)},
        open=False,
    )
    await POOL.open(wait=True, timeout=15)
    async with POOL.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price_cents INT NOT NULL,
                stock_qty INT NOT NULL
            )
            """
        )
        cur = await conn.execute("SELECT COUNT(*) FROM products")
        count = (await cur.fetchone())[0]
        if count == 0:
            log.info("seeding 5 products")
            for n, p, s in [("widget", 1999, 100), ("gadget", 499, 50),
                            ("sprocket", 299, 200), ("doohickey", 1299, 30),
                            ("thingamajig", 4999, 10)]:
                await conn.execute(
                    "INSERT INTO products(name,price_cents,stock_qty) VALUES(%s,%s,%s)",
                    (n, p, s),
                )
    log.info("startup complete")
    yield
    if POOL is not None:
        await POOL.close()


app = FastAPI(lifespan=lifespan)


class ProductIn(BaseModel):
    name: str
    price_cents: int
    stock_qty: int


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/products")
async def list_products():
    assert POOL is not None
    async with POOL.connection() as conn:
        cur = await conn.execute(
            "SELECT id,name,price_cents,stock_qty FROM products ORDER BY id"
        )
        rows = await cur.fetchall()
    return [{"id": r[0], "name": r[1], "price_cents": r[2], "stock_qty": r[3]} for r in rows]


@app.get("/products/{pid}")
async def get_product(pid: int):
    assert POOL is not None
    async with POOL.connection() as conn:
        cur = await conn.execute(
            "SELECT id,name,price_cents,stock_qty FROM products WHERE id=%s", (pid,)
        )
        r = await cur.fetchone()
    if r is None:
        raise HTTPException(404, "no such product")
    return {"id": r[0], "name": r[1], "price_cents": r[2], "stock_qty": r[3]}


@app.post("/products", status_code=201)
async def create_product(p: ProductIn):
    assert POOL is not None
    async with POOL.connection() as conn:
        cur = await conn.execute(
            "INSERT INTO products(name,price_cents,stock_qty) VALUES(%s,%s,%s) RETURNING id",
            (p.name, p.price_cents, p.stock_qty),
        )
        pid = (await cur.fetchone())[0]
    return {"id": pid}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_config=None)
