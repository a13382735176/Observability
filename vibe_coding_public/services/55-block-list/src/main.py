import logging, os, sys
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("block-list")

pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    try:
        pool = psycopg_pool.AsyncConnectionPool(
            os.environ.get("PG_DSN","postgres://vibe:vibe@postgres:5432/vibe"),
            min_size=1, max_size=5, open=False)
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS blocks("
                "id SERIAL PRIMARY KEY,"
                "blocker_id TEXT NOT NULL,"
                "blocked_id TEXT NOT NULL,"
                "created_at TIMESTAMPTZ DEFAULT NOW(),"
                "UNIQUE(blocker_id, blocked_id))")
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("block-list: db init failed: %s", e)
    yield
    if pool: await pool.close()

app = FastAPI(lifespan=lifespan)

class BlockIn(BaseModel):
    blocker_id: str
    blocked_id: str

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "block-list"}

@app.post("/block", status_code=201)
async def block_user(b: BlockIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO blocks(blocker_id,blocked_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING id,blocker_id,blocked_id,created_at",
                (b.blocker_id, b.blocked_id))
            row = await cur.fetchone()
            await conn.commit()
            if not row:
                return {"blocker_id": b.blocker_id, "blocked_id": b.blocked_id, "status": "already_blocked"}
            return {"id": row[0], "blocker_id": row[1], "blocked_id": row[2], "created_at": str(row[3])}
    except Exception as e:
        log.error("block-list: POST /block: %s", e)
        raise HTTPException(500, "internal error")

@app.delete("/block")
async def unblock_user(b: BlockIn):
    try:
        async with pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM blocks WHERE blocker_id=%s AND blocked_id=%s",
                (b.blocker_id, b.blocked_id))
            await conn.commit()
            return {"blocker_id": b.blocker_id, "blocked_id": b.blocked_id, "deleted": result.rowcount > 0}
    except Exception as e:
        log.error("block-list: DELETE /block: %s", e)
        raise HTTPException(500, "internal error")

@app.get("/blocked/{user_id}")
async def get_blocked(user_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT blocked_id, created_at FROM blocks WHERE blocker_id=%s ORDER BY id",
                (user_id,))).fetchall()
            return {"user_id": user_id, "count": len(rows), "blocked": [{"blocked_id": r[0], "created_at": str(r[1])} for r in rows]}
    except Exception as e:
        log.error("block-list: GET /blocked/%s: %s", user_id, e)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
