import logging, os, sys
from contextlib import asynccontextmanager
from typing import Optional

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("feedback-collector")

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
                "CREATE TABLE IF NOT EXISTS user_feedback("
                "id BIGSERIAL PRIMARY KEY,"
                "source TEXT NOT NULL,"
                "message TEXT NOT NULL,"
                "rating INT NOT NULL,"
                "user_id TEXT,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("feedback-collector: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class FeedbackIn(BaseModel):
    source: str
    message: str
    rating: int = Field(ge=1, le=5)
    user_id: Optional[str] = None


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "feedback-collector"}


@app.post("/feedback", status_code=201)
async def create_feedback(body: FeedbackIn):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO user_feedback(source,message,rating,user_id) "
                "VALUES(%s,%s,%s,%s) RETURNING id,source,message,rating,user_id,created_at",
                (body.source, body.message, body.rating, body.user_id),
            )).fetchone()
            await conn.commit()
    except Exception as e:
        log.error("feedback-collector: POST /feedback db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:feedback", {
            "id": str(row[0]),
            "rating": str(row[3]),
        })
    except Exception as e:
        log.error("feedback-collector: redis xadd events:feedback: %s", e)
    return {
        "id": row[0], "source": row[1], "message": row[2],
        "rating": row[3], "user_id": row[4], "created_at": str(row[5]),
    }


@app.get("/feedback/stats")
async def feedback_stats():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT source, AVG(rating)::float AS avg_rating, COUNT(*) AS cnt "
                "FROM user_feedback GROUP BY source ORDER BY source"
            )).fetchall()
        return {"by_source": [
            {"source": r[0], "avg_rating": r[1], "count": r[2]} for r in rows
        ]}
    except Exception as e:
        log.error("feedback-collector: GET /feedback/stats: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/feedback/by-source/{source}")
async def by_source(source: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,source,message,rating,user_id,created_at "
                "FROM user_feedback WHERE source=%s ORDER BY id DESC LIMIT 50",
                (source,),
            )).fetchall()
        return [
            {"id": r[0], "source": r[1], "message": r[2],
             "rating": r[3], "user_id": r[4], "created_at": str(r[5])}
            for r in rows
        ]
    except Exception as e:
        log.error("feedback-collector: GET /feedback/by-source/%s: %s", source, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/feedback/{fb_id}")
async def get_feedback(fb_id: int):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT id,source,message,rating,user_id,created_at "
                "FROM user_feedback WHERE id=%s",
                (fb_id,),
            )).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "id": row[0], "source": row[1], "message": row[2],
            "rating": row[3], "user_id": row[4], "created_at": str(row[5]),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("feedback-collector: GET /feedback/%s: %s", fb_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
