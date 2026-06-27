import asyncio, logging, os, sys
import asyncpg
from aiohttp import web

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("returns-processor")

pool = None

async def init_db(app):
    global pool
    try:
        pool = await asyncio.wait_for(
            asyncpg.create_pool(
                os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"),
                min_size=1, max_size=5),
            timeout=2.0)
        async with pool.acquire() as conn:
            await conn.execute(
                'CREATE TABLE IF NOT EXISTS returns ('
                '    id SERIAL PRIMARY KEY,'
                '    order_id TEXT NOT NULL,'
                '    reason TEXT,'
                "    status TEXT DEFAULT 'pending',"
                '    created_at TIMESTAMPTZ DEFAULT NOW()'
                ')'
            )
        log.info("postgres ready")
    except Exception as e:
        log.error("postgres init failed: %s", e)
    yield
    if pool:
        await pool.close()

async def healthz(req):
    return web.json_response({"status": "ok", "service": "returns-processor"})

async def get_returns(req):
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id,order_id,reason,status,created_at FROM returns ORDER BY id")
            return web.json_response([dict(r) for r in rows], dumps=lambda x: __import__("json").dumps(x, default=str))
    except Exception as e:
        log.error("GET /returns failed: %s", e)
        return web.json_response({"error": "internal error"}, status=500)

async def create_return(req):
    data = await req.json()
    order_id = data.get("order_id", "")
    reason = data.get("reason", "")
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO returns(order_id,reason) VALUES($1,$2) RETURNING id,order_id,reason,status,created_at",
                order_id, reason)
            return web.json_response(dict(row), status=201, dumps=lambda x: __import__("json").dumps(x, default=str))
    except Exception as e:
        log.error("POST /returns failed: %s", e)
        return web.json_response({"error": "internal error"}, status=500)

async def get_return_by_id(req):
    rid = int(req.match_info["id"])
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id,order_id,reason,status,created_at FROM returns WHERE id=$1", rid)
            if not row:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(dict(row), dumps=lambda x: __import__("json").dumps(x, default=str))
    except Exception as e:
        log.error("GET /returns/%s failed: %s", rid, e)
        return web.json_response({"error": "internal error"}, status=500)

app = web.Application()
app.cleanup_ctx.append(init_db)
app.router.add_get("/healthz", healthz)
app.router.add_get("/returns", get_returns)
app.router.add_post("/returns", create_return)
app.router.add_get("/returns/{id}", get_return_by_id)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8080)
