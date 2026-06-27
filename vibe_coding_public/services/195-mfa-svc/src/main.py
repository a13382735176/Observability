import logging, os, secrets, sys
from contextlib import asynccontextmanager

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
log = logging.getLogger("mfa-svc")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))

pool = psycopg_pool.AsyncConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, open=False,
    kwargs={"connect_timeout": 2},
)

rclient = redis.Redis(
    host=REDIS_CACHE_HOST, port=REDIS_CACHE_PORT,
    socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS mfa_enrollments("
                "user_id TEXT PRIMARY KEY,"
                "secret TEXT NOT NULL,"
                "enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS mfa_verifications("
                "id BIGSERIAL PRIMARY KEY,"
                "user_id TEXT NOT NULL,"
                "verified_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS backup_codes("
                "id BIGSERIAL PRIMARY KEY,"
                "user_id TEXT NOT NULL,"
                "code TEXT NOT NULL,"
                "used_at TIMESTAMPTZ,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("mfa-svc: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class EnrollIn(BaseModel):
    user_id: str


class VerifyIn(BaseModel):
    user_id: str
    code: str


class BackupUseIn(BaseModel):
    code: str


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "mfa-svc"}


@app.post("/enroll")
async def enroll(body: EnrollIn):
    secret = secrets.token_hex(20)
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO mfa_enrollments(user_id, secret) VALUES(%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET secret=EXCLUDED.secret, enrolled_at=now()",
                (body.user_id, secret),
            )
            await conn.commit()
    except Exception as e:
        log.error("mfa-svc: POST /enroll db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    qr_url = "otpauth://totp/Vibe:" + body.user_id + "?secret=" + secret
    return {"user_id": body.user_id, "secret": secret, "qr_url": qr_url}


@app.post("/verify")
async def verify(body: VerifyIn):
    if not (len(body.code) == 6 and body.code.isdigit()):
        raise HTTPException(status_code=400, detail="6-digit code required")
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT secret FROM mfa_enrollments WHERE user_id=%s",
                (body.user_id,),
            )).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="not enrolled")
            await conn.execute(
                "INSERT INTO mfa_verifications(user_id) VALUES(%s)",
                (body.user_id,),
            )
            await conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        log.error("mfa-svc: POST /verify db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.set("mfa_verified:" + body.user_id, "true", ex=600)
    except Exception as e:
        log.error("mfa-svc: POST /verify cache: %s", e)
    return {"user_id": body.user_id, "verified": True}


@app.get("/verified/{user_id}")
async def verified(user_id: str):
    try:
        v = rclient.get("mfa_verified:" + user_id)
    except Exception as e:
        log.error("mfa-svc: GET /verified/%s cache: %s", user_id, e)
        return JSONResponse(status_code=502, content={"error": "cache error"})
    return {"user_id": user_id, "verified": v == "true"}


@app.post("/backup-codes/{user_id}")
async def issue_backup_codes(user_id: str):
    codes = [secrets.token_hex(5) for _ in range(10)]
    try:
        async with pool.connection() as conn:
            for c in codes:
                await conn.execute(
                    "INSERT INTO backup_codes(user_id, code) VALUES(%s, %s)",
                    (user_id, c),
                )
            await conn.commit()
    except Exception as e:
        log.error("mfa-svc: POST /backup-codes/%s db: %s", user_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    return {"user_id": user_id, "codes": codes}


@app.post("/backup-codes/{user_id}/use")
async def use_backup_code(user_id: str, body: BackupUseIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE backup_codes SET used_at=now() "
                "WHERE user_id=%s AND code=%s AND used_at IS NULL",
                (user_id, body.code),
            )
            await conn.commit()
            used = (cur.rowcount or 0) > 0
    except Exception as e:
        log.error("mfa-svc: POST /backup-codes/%s/use db: %s", user_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    return {"user_id": user_id, "used": used}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
