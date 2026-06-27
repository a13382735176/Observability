import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("terraform-state")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")

pool = AsyncConnectionPool(
    conninfo=PG_DSN,
    min_size=1,
    max_size=4,
    timeout=2,
    open=False,
    kwargs={"connect_timeout": 2},
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await pool.open(wait=True, timeout=2)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_versions(
                        id bigserial PRIMARY KEY,
                        workspace text NOT NULL,
                        version int NOT NULL,
                        payload jsonb NOT NULL,
                        created_at timestamptz DEFAULT now(),
                        UNIQUE(workspace, version)
                    );
                    """
                )
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_locks(
                        workspace text PRIMARY KEY,
                        lock_id text NOT NULL,
                        locked_at timestamptz DEFAULT now()
                    );
                    """
                )
        log.info("terraform-state: postgres ready")
    except Exception as e:
        log.error("terraform-state: startup: %s", e)
    yield
    try:
        await pool.close()
    except Exception as e:
        log.error("terraform-state: shutdown: %s", e)


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "terraform-state"}


@app.post("/state/{workspace}")
async def put_state(workspace: str, request: Request):
    try:
        payload: Any = await request.json()
    except Exception as e:
        log.error("terraform-state: bad json: %s", e)
        return JSONResponse({"error": "bad json"}, status_code=400)
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM state_versions WHERE workspace = %s",
                    (workspace,),
                )
                row = await cur.fetchone()
                next_v = int(row[0]) if row else 1
                await cur.execute(
                    "INSERT INTO state_versions(workspace, version, payload) VALUES (%s, %s, %s::jsonb) RETURNING id, created_at",
                    (workspace, next_v, json.dumps(payload)),
                )
                ins = await cur.fetchone()
        return {
            "workspace": workspace,
            "version": next_v,
            "id": ins[0],
            "created_at": ins[1].isoformat() if ins and ins[1] else None,
        }
    except Exception as e:
        log.error("terraform-state: put_state: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


@app.get("/state/{workspace}")
async def get_state(workspace: str):
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT version, payload, created_at FROM state_versions WHERE workspace = %s ORDER BY version DESC LIMIT 1",
                    (workspace,),
                )
                row = await cur.fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {
            "workspace": workspace,
            "version": int(row[0]),
            "payload": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
        }
    except Exception as e:
        log.error("terraform-state: get_state: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


@app.get("/state/{workspace}/versions")
async def list_versions(workspace: str):
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT version, created_at FROM state_versions WHERE workspace = %s ORDER BY version DESC",
                    (workspace,),
                )
                rows = await cur.fetchall()
        return {
            "workspace": workspace,
            "versions": [
                {"version": int(r[0]), "created_at": r[1].isoformat() if r[1] else None}
                for r in rows
            ],
        }
    except Exception as e:
        log.error("terraform-state: list_versions: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


@app.get("/state/{workspace}/version/{version}")
async def get_version(workspace: str, version: int):
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT version, payload, created_at FROM state_versions WHERE workspace = %s AND version = %s",
                    (workspace, version),
                )
                row = await cur.fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        return {
            "workspace": workspace,
            "version": int(row[0]),
            "payload": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
        }
    except Exception as e:
        log.error("terraform-state: get_version: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


@app.post("/state/{workspace}/lock")
async def acquire_lock(workspace: str, request: Request):
    try:
        body = await request.json()
    except Exception as e:
        log.error("terraform-state: bad lock json: %s", e)
        return JSONResponse({"error": "bad json"}, status_code=400)
    lock_id = body.get("lock_id") if isinstance(body, dict) else None
    if not lock_id:
        return JSONResponse({"error": "lock_id required"}, status_code=400)
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO state_locks(workspace, lock_id) VALUES (%s, %s) "
                    "ON CONFLICT (workspace) DO NOTHING "
                    "RETURNING lock_id, locked_at",
                    (workspace, lock_id),
                )
                row = await cur.fetchone()
                if row is None:
                    await cur.execute(
                        "SELECT lock_id, locked_at FROM state_locks WHERE workspace = %s",
                        (workspace,),
                    )
                    held = await cur.fetchone()
                    return JSONResponse(
                        {
                            "error": "locked",
                            "workspace": workspace,
                            "lock_id": held[0] if held else None,
                            "locked_at": held[1].isoformat() if held and held[1] else None,
                        },
                        status_code=409,
                    )
        return {
            "workspace": workspace,
            "lock_id": row[0],
            "locked_at": row[1].isoformat() if row[1] else None,
        }
    except Exception as e:
        log.error("terraform-state: acquire_lock: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


@app.delete("/state/{workspace}/lock/{lock_id}")
async def release_lock(workspace: str, lock_id: str):
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM state_locks WHERE workspace = %s AND lock_id = %s RETURNING workspace",
                    (workspace, lock_id),
                )
                row = await cur.fetchone()
        if not row:
            return JSONResponse({"error": "not locked or wrong lock_id"}, status_code=404)
        return {"workspace": workspace, "released": True}
    except Exception as e:
        log.error("terraform-state: release_lock: %s", e)
        return JSONResponse({"error": "error"}, status_code=503)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
