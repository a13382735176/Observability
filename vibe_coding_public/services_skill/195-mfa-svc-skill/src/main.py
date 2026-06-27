import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import contextmanager
from typing import Optional

import psycopg
import redis
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

APP_NAME = os.getenv("APP_NAME", "mfa-svc-skill")
PG_DSN = os.getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.getenv("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.getenv("REDIS_CACHE_PORT", "6379"))
SERVICE_NAME = "mfa-svc"

logger = logging.getLogger("mfa_svc")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

app = FastAPI(title=APP_NAME)
_redis_client: Optional[redis.Redis] = None


class EnrollRequest(BaseModel):
    user_id: str


class VerifyRequest(BaseModel):
    user_id: str
    code: str


class UseBackupCodeRequest(BaseModel):
    code: str


def user_ref(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def log_event(level: int, event: str, **fields) -> None:
    payload = {"service": SERVICE_NAME, "app": APP_NAME, "event": event, **fields}
    logger.log(level, json.dumps(payload, separators=(",", ":"), default=str))


@contextmanager
def timed_operation(operation: str, **fields):
    start = time.perf_counter()
    try:
        yield
        log_event(logging.INFO, "operation_complete", operation=operation,
                  latency_ms=round((time.perf_counter() - start) * 1000, 2), **fields)
    except Exception as exc:
        log_event(logging.ERROR, "operation_failed", operation=operation,
                  error_type=type(exc).__name__,
                  latency_ms=round((time.perf_counter() - start) * 1000, 2), **fields)
        raise


@contextmanager
def db_conn():
    with psycopg.connect(PG_DSN) as conn:
        yield conn


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_CACHE_HOST,
            port=REDIS_CACHE_PORT,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def init_db() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS mfa_enrollments(
            user_id TEXT PRIMARY KEY,
            secret TEXT NOT NULL,
            enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS mfa_verifications(
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS backup_codes(
            id BIGSERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            code TEXT NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]
    with timed_operation("startup_db_init"):
        with db_conn() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
            conn.commit()


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        log_event(
            logging.INFO,
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return response
    except Exception as exc:
        log_event(
            logging.ERROR,
            "http_request_failed",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        raise


@app.on_event("startup")
def on_startup() -> None:
    log_event(logging.INFO, "service_starting", port=8080)
    init_db()
    log_event(logging.INFO, "service_started", port=8080)


@app.on_event("shutdown")
def on_shutdown() -> None:
    if _redis_client is not None:
        _redis_client.close()
    log_event(logging.INFO, "service_stopped")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/enroll")
def enroll(req: EnrollRequest):
    secret = secrets.token_hex(20)
    with timed_operation("enroll", user=user_ref(req.user_id)):
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mfa_enrollments(user_id, secret)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET secret = EXCLUDED.secret, enrolled_at = now()
                    """,
                    (req.user_id, secret),
                )
            conn.commit()
    return {"secret": secret, "qr_url": f"otpauth://totp/Vibe:{req.user_id}?secret={secret}"}


@app.post("/verify")
def verify(req: VerifyRequest):
    if len(req.code) != 6 or not req.code.isdigit():
        raise HTTPException(status_code=400, detail="code must be 6 digits")

    with timed_operation("verify", user=user_ref(req.user_id)):
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO mfa_verifications(user_id) VALUES (%s)", (req.user_id,))
            conn.commit()
        get_redis().set(f"mfa_verified:{req.user_id}", "1", ex=600)
    return {"verified": True}


@app.get("/verified/{user_id}")
def verified(user_id: str):
    with timed_operation("verified_lookup", user=user_ref(user_id)):
        value = get_redis().get(f"mfa_verified:{user_id}")
    return {"verified": value is not None}


@app.post("/backup-codes/{user_id}")
def create_backup_codes(user_id: str):
    codes = [secrets.token_hex(5) for _ in range(10)]
    with timed_operation("backup_codes_create", user=user_ref(user_id), count=len(codes)):
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO backup_codes(user_id, code) VALUES (%s, %s)",
                    [(user_id, code) for code in codes],
                )
            conn.commit()
    return {"codes": codes}


@app.post("/backup-codes/{user_id}/use")
def use_backup_code(user_id: str, req: UseBackupCodeRequest):
    with timed_operation("backup_code_use", user=user_ref(user_id)):
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE backup_codes
                    SET used_at = now()
                    WHERE user_id = %s AND code = %s AND used_at IS NULL
                    """,
                    (user_id, req.code),
                )
                used = cur.rowcount > 0
            conn.commit()
    return {"used": used}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
