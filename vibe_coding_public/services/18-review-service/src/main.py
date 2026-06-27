import logging, os, sys
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("review-service")

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
                'CREATE TABLE IF NOT EXISTS reviews ('
                '    id SERIAL PRIMARY KEY,'
                '    product_id INT NOT NULL,'
                '    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),'
                '    body TEXT,'
                '    created_at TIMESTAMPTZ DEFAULT NOW()'
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

class ReviewIn(BaseModel):
    product_id: int
    rating: int
    body: str = ""

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "review-service"}

@app.get("/reviews/{product_id}")
async def get_reviews(product_id: int):
    try:
        async with pool.connection() as conn:
            rows = await conn.execute(
                "SELECT id,product_id,rating,body,created_at FROM reviews WHERE product_id=%s ORDER BY id",
                (product_id,))
            data = await rows.fetchall()
            cols = ["id","product_id","rating","body","created_at"]
            return [dict(zip(cols, r)) for r in data]
    except Exception as e:
        log.error("GET /reviews/%s failed: %s", product_id, e)
        raise HTTPException(500, "internal error")

@app.post("/reviews", status_code=201)
async def post_review(r: ReviewIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO reviews(product_id,rating,body) VALUES(%s,%s,%s) RETURNING id,product_id,rating,body,created_at",
                (r.product_id, r.rating, r.body))
            row = await cur.fetchone()
            await conn.commit()
            cols = ["id","product_id","rating","body","created_at"]
            return dict(zip(cols, row))
    except Exception as e:
        log.error("POST /reviews failed: %s", e)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
