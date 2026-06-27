import logging, os, sys
import asyncpg, httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("kyc-verifier")

pool = None
UPSTREAM = "http://mock-upstream:8080"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    dsn = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
    try:
        pool = await asyncpg.create_pool(dsn, command_timeout=2, min_size=1, max_size=5)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS kyc_records(
                    id serial PRIMARY KEY,
                    user_id text,
                    status text,
                    doc_type text,
                    verified_at timestamptz
                )
            """)
        log.info("kyc-verifier: postgres ready")
    except Exception as e:
        log.error(f"kyc-verifier: pg init: {e}")
    yield
    if pool: await pool.close()

app = FastAPI(lifespan=lifespan)

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "kyc-verifier"}

class VerifyReq(BaseModel):
    user_id: str
    doc_type: str
    doc_number: str

@app.post("/verify", status_code=201)
async def verify(req: VerifyReq):
    status = "failed"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(f"{UPSTREAM}/verify", json={"doc_type": req.doc_type, "doc_number": req.doc_number})
            if resp.status_code == 200:
                status = "verified"
    except Exception as e:
        log.error(f"kyc-verifier: upstream: {e}")
    try:
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO kyc_records(user_id, status, doc_type, verified_at) VALUES($1,$2,$3,$4)
                   ON CONFLICT DO NOTHING""",
                req.user_id, status, req.doc_type, now if status == "verified" else None
            )
    except Exception as e:
        log.error(f"kyc-verifier: pg: {e}")
        raise HTTPException(503, "db error")
    return {"user_id": req.user_id, "status": status}

@app.get("/status/{user_id}")
async def get_status(user_id: str):
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id,user_id,status,doc_type,verified_at FROM kyc_records WHERE user_id=$1 ORDER BY id DESC LIMIT 5",
                user_id
            )
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"kyc-verifier: pg: {e}")
        raise HTTPException(503, "db error")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
