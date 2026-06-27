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
log = logging.getLogger("hotel-booking")

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
                "CREATE TABLE IF NOT EXISTS hotel_bookings("
                "id SERIAL PRIMARY KEY,"
                "hotel_id TEXT NOT NULL,"
                "user_id TEXT NOT NULL,"
                "checkin_date DATE NOT NULL,"
                "checkout_date DATE NOT NULL,"
                "rooms INT NOT NULL DEFAULT 1,"
                "status TEXT NOT NULL DEFAULT 'confirmed',"
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            await conn.commit()
        log.info("db init ok")
    except Exception as e:
        log.error("hotel-booking: db init failed: %s", e)
    yield
    try:
        await pool.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


class BookingIn(BaseModel):
    hotel_id: str
    user_id: str
    checkin_date: str
    checkout_date: str
    rooms: Optional[int] = 1


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "hotel-booking"}


@app.post("/bookings", status_code=201)
async def create_booking(body: BookingIn):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "INSERT INTO hotel_bookings(hotel_id,user_id,checkin_date,checkout_date,rooms) "
                "VALUES(%s,%s,%s,%s,%s) RETURNING id,hotel_id,user_id,checkin_date,checkout_date,rooms,status,created_at",
                (body.hotel_id, body.user_id, body.checkin_date, body.checkout_date, body.rooms or 1),
            )).fetchone()
            await conn.commit()
    except Exception as e:
        log.error("hotel-booking: POST /bookings db: %s", e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:bookings", {
            "event": "booking_created",
            "booking_id": str(row[0]),
            "hotel_id": row[1],
            "user_id": row[2],
        })
    except Exception as e:
        log.error("hotel-booking: redis xadd booking_created: %s", e)
    return {
        "id": row[0], "hotel_id": row[1], "user_id": row[2],
        "checkin_date": str(row[3]), "checkout_date": str(row[4]),
        "rooms": row[5], "status": row[6], "created_at": str(row[7]),
    }


@app.get("/bookings/{user_id}")
async def list_user_bookings(user_id: str):
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT id,hotel_id,user_id,checkin_date,checkout_date,rooms,status,created_at "
                "FROM hotel_bookings WHERE user_id=%s ORDER BY id DESC LIMIT 20",
                (user_id,),
            )).fetchall()
        return [
            {"id": r[0], "hotel_id": r[1], "user_id": r[2],
             "checkin_date": str(r[3]), "checkout_date": str(r[4]),
             "rooms": r[5], "status": r[6], "created_at": str(r[7])}
            for r in rows
        ]
    except Exception as e:
        log.error("hotel-booking: GET /bookings/%s: %s", user_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})


@app.put("/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: int):
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "UPDATE hotel_bookings SET status='cancelled' WHERE id=%s "
                "RETURNING id,hotel_id,user_id,checkin_date,checkout_date,rooms,status,created_at",
                (booking_id,),
            )).fetchone()
            await conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
    except HTTPException:
        raise
    except Exception as e:
        log.error("hotel-booking: PUT /bookings/%s/cancel db: %s", booking_id, e)
        return JSONResponse(status_code=503, content={"error": "internal error"})
    try:
        rclient.xadd("events:bookings", {
            "event": "booking_cancelled",
            "booking_id": str(row[0]),
            "hotel_id": row[1],
            "user_id": row[2],
        })
    except Exception as e:
        log.error("hotel-booking: redis xadd booking_cancelled: %s", e)
    return {
        "id": row[0], "hotel_id": row[1], "user_id": row[2],
        "checkin_date": str(row[3]), "checkout_date": str(row[4]),
        "rooms": row[5], "status": row[6], "created_at": str(row[7]),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
