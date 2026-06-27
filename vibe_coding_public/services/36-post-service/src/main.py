import logging, os, sys, json
import psycopg_pool, redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("post-service")

pool = None
rstream = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, rstream
    try:
        pool = psycopg_pool.AsyncConnectionPool(
            os.environ.get("PG_DSN","postgres://vibe:vibe@postgres:5432/vibe"),
            min_size=1, max_size=5, open=False)
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS posts("
                "id SERIAL PRIMARY KEY, user_id TEXT NOT NULL,"
                "content TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())")
            await conn.commit()
        log.info("postgres ready")
    except Exception as e:
        log.error("post-service: postgres init failed: %s", e)
    try:
        rstream = aioredis.Redis(
            host=os.environ.get("REDIS_STREAM_HOST","redis-stream"),
            port=int(os.environ.get("REDIS_STREAM_PORT","6379")),
            socket_connect_timeout=2, decode_responses=True)
        await rstream.ping()
        log.info("redis-stream ready")
    except Exception as e:
        log.error("post-service: redis-stream init failed: %s", e)
    yield
    if pool: await pool.close()
    if rstream: await rstream.close()

app = FastAPI(lifespan=lifespan)

class PostIn(BaseModel):
    user_id: str
    content: str

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "post-service"}

@app.get("/posts")
async def list_posts():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute("SELECT id,user_id,content,created_at FROM posts ORDER BY id DESC LIMIT 50")).fetchall()
            return [{"id": r[0], "user_id": r[1], "content": r[2], "created_at": str(r[3])} for r in rows]
    except Exception as e:
        log.error("post-service: GET /posts: %s", e)
        raise HTTPException(500, "internal error")

@app.post("/posts", status_code=201)
async def create_post(p: PostIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO posts(user_id,content) VALUES(%s,%s) RETURNING id,user_id,content,created_at",
                (p.user_id, p.content))
            row = await cur.fetchone()
            await conn.commit()
        post = {"id": row[0], "user_id": row[1], "content": row[2], "created_at": str(row[3])}
        try:
            await rstream.xadd("events:posts", {"event": "post.created", "payload": json.dumps(post)})
        except Exception as e:
            log.error("post-service: stream publish failed: %s", e)
        return post
    except Exception as e:
        log.error("post-service: POST /posts: %s", e)
        raise HTTPException(500, "internal error")

@app.get("/posts/{post_id}")
async def get_post(post_id: int):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT id,user_id,content,created_at FROM posts WHERE id=%s", (post_id,))
            row = await cur.fetchone()
            if not row: raise HTTPException(404, "not found")
            return {"id": row[0], "user_id": row[1], "content": row[2], "created_at": str(row[3])}
    except HTTPException: raise
    except Exception as e:
        log.error("post-service: GET /posts/%s: %s", post_id, e)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
