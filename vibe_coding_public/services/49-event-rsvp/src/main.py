import logging, os, sys
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("event-rsvp")

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
            await conn.execute("CREATE TABLE IF NOT EXISTS events(id SERIAL PRIMARY KEY,"
                "title TEXT NOT NULL, host_id TEXT NOT NULL,"
                "start_time TIMESTAMPTZ, max_guests INT DEFAULT 100)")
            await conn.execute("CREATE TABLE IF NOT EXISTS rsvps(id SERIAL PRIMARY KEY,"
                "event_id INT NOT NULL REFERENCES events(id), user_id TEXT NOT NULL,"
                "created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(event_id, user_id))")
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("event-rsvp: db init failed: %s", e)
    yield
    if pool: await pool.close()

app = FastAPI(lifespan=lifespan)

class EventIn(BaseModel):
    title: str
    host_id: str
    start_time: Optional[str] = None
    max_guests: int = 100

class RsvpIn(BaseModel):
    event_id: int
    user_id: str

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "event-rsvp"}

@app.post("/events", status_code=201)
async def create_event(e: EventIn):
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO events(title,host_id,start_time,max_guests) VALUES(%s,%s,%s::timestamptz,%s) RETURNING id,title,host_id,start_time,max_guests",
                (e.title, e.host_id, e.start_time, e.max_guests))
            row = await cur.fetchone()
            await conn.commit()
            return {"id": row[0], "title": row[1], "host_id": row[2], "start_time": str(row[3]), "max_guests": row[4]}
    except Exception as ex:
        log.error("event-rsvp: POST /events: %s", ex)
        raise HTTPException(500, "internal error")

@app.post("/rsvp", status_code=201)
async def rsvp(r: RsvpIn):
    try:
        async with pool.connection() as conn:
            # check capacity
            cur = await conn.execute("SELECT max_guests FROM events WHERE id=%s", (r.event_id,))
            ev = await cur.fetchone()
            if not ev: raise HTTPException(404, "event not found")
            cur2 = await conn.execute("SELECT COUNT(*) FROM rsvps WHERE event_id=%s", (r.event_id,))
            count = (await cur2.fetchone())[0]
            if count >= ev[0]: raise HTTPException(409, "event full")
            cur3 = await conn.execute(
                "INSERT INTO rsvps(event_id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING id,event_id,user_id,created_at",
                (r.event_id, r.user_id))
            row = await cur3.fetchone()
            await conn.commit()
            if not row: raise HTTPException(409, "already rsvped")
            return {"id": row[0], "event_id": row[1], "user_id": row[2], "created_at": str(row[3])}
    except HTTPException: raise
    except Exception as ex:
        log.error("event-rsvp: POST /rsvp: %s", ex)
        raise HTTPException(500, "internal error")

@app.get("/events/{event_id}/guests")
async def get_guests(event_id: int):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute("SELECT user_id,created_at FROM rsvps WHERE event_id=%s ORDER BY id", (event_id,))).fetchall()
            return {"event_id": event_id, "count": len(rows), "guests": [{"user_id": r[0], "created_at": str(r[1])} for r in rows]}
    except Exception as ex:
        log.error("event-rsvp: GET /events/%s/guests: %s", event_id, ex)
        raise HTTPException(500, "internal error")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
