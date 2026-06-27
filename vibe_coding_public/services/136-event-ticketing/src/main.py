import logging, os, sys
from contextlib import asynccontextmanager
from typing import Optional

import psycopg_pool
import redis
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("event-ticketing")

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
                "CREATE TABLE IF NOT EXISTS events("
                "id SERIAL PRIMARY KEY,"
                "name TEXT NOT NULL,"
                "venue TEXT NOT NULL,"
                "event_time TIMESTAMPTZ NOT NULL,"
                "total_tickets INT NOT NULL,"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS tickets("
                "id SERIAL PRIMARY KEY,"
                "event_id INT NOT NULL,"
                "user_id TEXT NOT NULL,"
                "quantity INT NOT NULL DEFAULT 1,"
                "purchased_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("event-ticketing: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class EventIn(BaseModel):
    name: str
    venue: str
    event_time: str
    total_tickets: int


class TicketIn(BaseModel):
    event_id: int
    user_id: str
    quantity: Optional[int] = 1


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "event-ticketing"}


@app.post("/events", status_code=201)
async def create_event(body: EventIn):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO events(name,venue,event_time,total_tickets) "
                "VALUES(%s,%s,%s,%s) RETURNING id,name,venue,event_time,total_tickets,created_at",
                (body.name, body.venue, body.event_time, body.total_tickets),
            )).fetchone()
            await conn.commit()
        return {
            "id": row[0], "name": row[1], "venue": row[2],
            "event_time": str(row[3]), "total_tickets": row[4],
            "created_at": str(row[5]),
        }
    except Exception as e:
        log.error("event-ticketing: POST /events: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.post("/tickets/buy", status_code=201)
async def buy_ticket(body: TicketIn):
    qty = body.quantity or 1
    try:
        async with pool.connection() as conn:
            ev = await (await conn.execute(
                "SELECT id,total_tickets FROM events WHERE id=%s",
                (body.event_id,),
            )).fetchone()
            if not ev:
                raise HTTPException(status_code=404, detail="event not found")
            sold = await (await conn.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM tickets WHERE event_id=%s",
                (body.event_id,),
            )).fetchone()
            sold_count = int(sold[0] or 0)
            if sold_count + qty > ev[1]:
                return JSONResponse(
                    status_code=409,
                    content={"error": "sold out", "sold": sold_count, "total": ev[1]},
                )
            row = await (await conn.execute(
                "INSERT INTO tickets(event_id,user_id,quantity) VALUES(%s,%s,%s) "
                "RETURNING id,event_id,user_id,quantity,purchased_at",
                (body.event_id, body.user_id, qty),
            )).fetchone()
            await conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        log.error("event-ticketing: POST /tickets/buy db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:ticket_sales", {
            "event": "ticket_sold",
            "ticket_id": str(row[0]),
            "event_id": str(row[1]),
            "user_id": row[2],
            "quantity": str(row[3]),
        })
    except Exception as e:
        log.error("event-ticketing: redis xadd ticket_sold: %s", e)
    return {
        "id": row[0], "event_id": row[1], "user_id": row[2],
        "quantity": row[3], "purchased_at": str(row[4]),
    }


@app.get("/events/{event_id}")
async def get_event(event_id: int):
    try:
        async with pool.connection() as conn:
            ev = await (await conn.execute(
                "SELECT id,name,venue,event_time,total_tickets,created_at FROM events WHERE id=%s",
                (event_id,),
            )).fetchone()
            if not ev:
                raise HTTPException(status_code=404, detail="event not found")
            sold = await (await conn.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM tickets WHERE event_id=%s",
                (event_id,),
            )).fetchone()
        sold_count = int(sold[0] or 0)
        return {
            "id": ev[0], "name": ev[1], "venue": ev[2],
            "event_time": str(ev[3]), "total_tickets": ev[4],
            "created_at": str(ev[5]),
            "sold": sold_count, "remaining": max(ev[4] - sold_count, 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("event-ticketing: GET /events/%s: %s", event_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.get("/tickets/{user_id}")
async def list_user_tickets(user_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,event_id,user_id,quantity,purchased_at FROM tickets "
                "WHERE user_id=%s ORDER BY id DESC LIMIT 20",
                (user_id,),
            )).fetchall()
        return [
            {"id": r[0], "event_id": r[1], "user_id": r[2],
             "quantity": r[3], "purchased_at": str(r[4])}
            for r in rows
        ]
    except Exception as e:
        log.error("event-ticketing: GET /tickets/%s: %s", user_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
