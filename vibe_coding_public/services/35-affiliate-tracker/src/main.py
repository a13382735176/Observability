import logging, os, sys
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("affiliate-tracker")

pool: psycopg_pool.AsyncConnectionPool | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    try:
        pool = psycopg_pool.AsyncConnectionPool(
            os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"),
            min_size=1, max_size=5, open=False)
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                'CREATE TABLE IF NOT EXISTS affiliates ('
                '    id SERIAL PRIMARY KEY,'
                '    code TEXT UNIQUE NOT NULL,'
                '    commission_pct INT NOT NULL,'
                '    clicks INT DEFAULT 0'
                ')'
            )
            await conn.commit()
        log.info("postgres ready")
    except Exception as e:
        log.error("postgres init failed: %s", e)
    yield
    if pool:
        await pool.close()

app = FastAPI(lifespan=lifespan)

class AffiliateIn(BaseModel):
    code: str
    commission_pct: int

class ClickIn(BaseModel):
    affiliate_code: str
    product_id: int

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "affiliate-tracker"}

@app.get("/affiliates")
async def get_affiliates():
    try:
        async with pool.connection() as conn:
            rows = await conn.execute("SELECT id,code,commission_pct,clicks FROM affiliates ORDER BY id")
            data = await rows.fetchall()
            return [{"id": r[0], "code": r[1], "commission_pct": r[2], "clicks": r[3]} for r in data]
    except Exception as e:
        log.error("GET /affiliates failed: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/affiliates", status_code=201)
async def create_affiliate(a: AffiliateIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO affiliates(code,commission_pct) VALUES(%s,%s) RETURNING id,code,commission_pct,clicks",
                (a.code, a.commission_pct))
            row = await cur.fetchone()
            await conn.commit()
            return {"id": row[0], "code": row[1], "commission_pct": row[2], "clicks": row[3]}
    except Exception as e:
        log.error("POST /affiliates failed: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/click", status_code=201)
async def record_click(c: ClickIn):
    try:
        async with pool.connection() as conn:
            result = await conn.execute(
                "UPDATE affiliates SET clicks=clicks+1 WHERE code=%s",
                (c.affiliate_code,))
            await conn.commit()
            if result.rowcount == 0:
                raise HTTPException(404, "affiliate not found")
            return {"affiliate_code": c.affiliate_code, "product_id": c.product_id, "recorded": True}
    except HTTPException:
        raise
    except Exception as e:
        log.error("POST /click failed: %s", e)
        raise HTTPException(500, "internal error")

@app.get("/stats/{code}")
async def get_stats(code: str):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id,code,commission_pct,clicks FROM affiliates WHERE code=%s", (code,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "affiliate not found")
            return {"id": row[0], "code": row[1], "commission_pct": row[2], "clicks": row[3]}
    except HTTPException:
        raise
    except Exception as e:
        log.error("GET /stats/%s failed: %s", code, e)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
