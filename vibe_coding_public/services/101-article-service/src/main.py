import logging, os, sys, json
import psycopg_pool, redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("article-service")

pool = None
rcache = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, rcache
    try:
        pool = psycopg_pool.AsyncConnectionPool(
            os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"),
            min_size=1, max_size=5, open=False)
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS articles("
                "id SERIAL PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,"
                "author_id TEXT NOT NULL, published_at TIMESTAMPTZ DEFAULT NOW())")
            await conn.commit()
        log.info("postgres ready")
    except Exception as e:
        log.error("article-service: postgres init failed: %s", e)
    try:
        rcache = aioredis.Redis(
            host=os.environ.get("REDIS_CACHE_HOST", "redis-cache"),
            port=int(os.environ.get("REDIS_CACHE_PORT", "6379")),
            socket_connect_timeout=2, decode_responses=True)
        await rcache.ping()
        log.info("redis-cache ready")
    except Exception as e:
        log.error("article-service: redis-cache init failed: %s", e)
    yield
    if pool: await pool.close()
    if rcache: await rcache.aclose()

app = FastAPI(lifespan=lifespan)

class ArticleIn(BaseModel):
    title: str
    content: str
    author_id: str

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "article-service"}

@app.get("/articles")
async def list_articles():
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,title,content,author_id,published_at FROM articles ORDER BY id DESC LIMIT 50"
            )).fetchall()
        return [{"id": r[0], "title": r[1], "content": r[2], "author_id": r[3], "published_at": str(r[4])} for r in rows]
    except Exception as e:
        log.error("article-service: GET /articles: %s", e)
        raise HTTPException(502, "postgres error")

@app.post("/articles", status_code=201)
async def create_article(a: ArticleIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO articles(title,content,author_id) VALUES(%s,%s,%s) RETURNING id,title,content,author_id,published_at",
                (a.title, a.content, a.author_id))
            row = await cur.fetchone()
            await conn.commit()
        art = {"id": row[0], "title": row[1], "content": row[2], "author_id": row[3], "published_at": str(row[4])}
        try:
            await rcache.set(f"art:{art['id']}", json.dumps(art), ex=300)
        except Exception as e:
            log.error("article-service: cache set failed: %s", e)
        return art
    except Exception as e:
        log.error("article-service: POST /articles: %s", e)
        raise HTTPException(502, "postgres error")

@app.get("/articles/{article_id}")
async def get_article(article_id: int):
    try:
        cached = await rcache.get(f"art:{article_id}")
        if cached:
            return json.loads(cached)
    except Exception as e:
        log.error("article-service: cache get failed: %s", e)
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id,title,content,author_id,published_at FROM articles WHERE id=%s", (article_id,))
            row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "not found")
        return {"id": row[0], "title": row[1], "content": row[2], "author_id": row[3], "published_at": str(row[4])}
    except HTTPException:
        raise
    except Exception as e:
        log.error("article-service: GET /articles/%s: %s", article_id, e)
        raise HTTPException(502, "postgres error")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
