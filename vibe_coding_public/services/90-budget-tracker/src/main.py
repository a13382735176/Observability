import asyncio, logging, os
from aiohttp import web
import psycopg_pool
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")

pool: psycopg_pool.AsyncConnectionPool
redis: aioredis.Redis

async def init_db():
    async with pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets(
                id serial PRIMARY KEY,
                user_id text,
                category text,
                limit_cents bigint,
                period text,
                UNIQUE(user_id, category)
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id serial PRIMARY KEY,
                user_id text,
                category text,
                amount_cents bigint,
                ts timestamptz DEFAULT now()
            )""")
        await conn.commit()

async def healthz(request):
    return web.json_response({"status": "ok", "service": "budget-tracker"})

async def create_budget(request):
    data = await request.json()
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO budgets(user_id,category,limit_cents,period) VALUES(%s,%s,%s,%s)"
                " ON CONFLICT(user_id,category) DO UPDATE SET limit_cents=EXCLUDED.limit_cents,period=EXCLUDED.period"
                " RETURNING id,user_id,category,limit_cents,period",
                (data["user_id"], data["category"], int(data["limit_cents"]), data.get("period","monthly"))
            )).fetchone()
            await conn.commit()
        cols = ["id","user_id","category","limit_cents","period"]
        return web.json_response(dict(zip(cols, row)), status=201)
    except Exception as e:
        log.error("budget-tracker: %s", e)
        return web.json_response({"error": "db error"}, status=503)

async def add_expense(request):
    data = await request.json()
    try:
        user_id = data["user_id"]
        category = data["category"]
        amount = int(data["amount_cents"])
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO expenses(user_id,category,amount_cents) VALUES(%s,%s,%s)",
                (user_id, category, amount)
            )
            await conn.commit()
        key = f"spent:{user_id}:{category}"
        await redis.incrby(key, amount)
        await redis.expire(key, 86400)
        return web.json_response({"ok": True, "user_id": user_id, "category": category, "amount_cents": amount}, status=201)
    except Exception as e:
        log.error("budget-tracker: %s", e)
        return web.json_response({"error": "error"}, status=503)

async def budget_status(request):
    user_id = request.match_info["user_id"]
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT category,limit_cents,period FROM budgets WHERE user_id=%s",
                (user_id,)
            )).fetchall()
        result = []
        for (category, limit, period) in rows:
            key = f"spent:{user_id}:{category}"
            spent_raw = await redis.get(key)
            spent = int(spent_raw) if spent_raw else 0
            result.append({"category": category, "limit_cents": limit, "spent_cents": spent, "period": period, "over_budget": spent > limit})
        return web.json_response(result)
    except Exception as e:
        log.error("budget-tracker: %s", e)
        return web.json_response({"error": "db error"}, status=503)

async def create_app():
    global pool, redis
    pool = psycopg_pool.AsyncConnectionPool(PG_DSN, min_size=1, max_size=5, timeout=2.0, open=False)
    await pool.open()
    redis = aioredis.Redis(host=CACHE_HOST, port=6379, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
    try:
        await init_db()
    except Exception as e:
        log.error("budget-tracker: %s", e)
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_post("/budgets", create_budget)
    app.router.add_post("/expenses", add_expense)
    app.router.add_get("/budgets/{user_id}/status", budget_status)
    return app

if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8080)
