import logging
import os
import sys
from datetime import datetime, timezone

import psycopg
import psycopg_pool
import redis
from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("support-ticket")

SERVICE = "support-ticket"
PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))
OPEN_TICKETS_KEY = "open_tickets"

pool = psycopg_pool.ConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, kwargs={"connect_timeout": 2}
)

r = redis.Redis(
    host=REDIS_CACHE_HOST,
    port=REDIS_CACHE_PORT,
    socket_timeout=2,
    socket_connect_timeout=2,
    decode_responses=True,
)

DDL = """
CREATE TABLE IF NOT EXISTS support_tickets(
    id bigserial PRIMARY KEY,
    user_id text,
    subject text,
    body text,
    priority int DEFAULT 3,
    status text DEFAULT 'open',
    created_at timestamptz DEFAULT now()
)
"""

try:
    with pool.connection() as conn:
        conn.execute(DDL)
        conn.commit()
    log.info("support-ticket: db init ok")
except Exception as e:
    log.error("support-ticket: db init: %s", e)

app = Flask(__name__)


def _row_to_dict(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "subject": row[2],
        "body": row[3],
        "priority": row[4],
        "status": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
    }


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": SERVICE})


@app.post("/tickets")
def create_ticket():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    subject = body.get("subject")
    text = body.get("body")
    priority = body.get("priority", 3)
    if not user_id or not subject or text is None:
        return jsonify({"error": "user_id, subject, body required"}), 400
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO support_tickets(user_id, subject, body, priority)
                VALUES (%s, %s, %s, %s)
                RETURNING id, user_id, subject, body, priority, status, created_at
                """,
                (user_id, subject, text, priority),
            ).fetchone()
            conn.commit()
        ticket = _row_to_dict(row)
        try:
            r.sadd(OPEN_TICKETS_KEY, str(ticket["id"]))
        except Exception as e:
            log.error("support-ticket: cache sadd: %s", e)
        return jsonify(ticket), 201
    except Exception as e:
        log.error("support-ticket: POST /tickets: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/tickets/<int:tid>")
def get_ticket(tid):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT id, user_id, subject, body, priority, status, created_at FROM support_tickets WHERE id=%s",
                (tid,),
            ).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(_row_to_dict(row))
    except Exception as e:
        log.error("support-ticket: GET /tickets/<id>: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/tickets/open")
def list_open():
    try:
        ids = r.smembers(OPEN_TICKETS_KEY)
        if ids:
            id_list = [int(i) for i in ids]
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT id, user_id, subject, body, priority, status, created_at FROM support_tickets WHERE id = ANY(%s) ORDER BY id DESC",
                    (id_list,),
                ).fetchall()
            return jsonify([_row_to_dict(row) for row in rows])
    except Exception as e:
        log.error("support-ticket: cache smembers: %s", e)
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, subject, body, priority, status, created_at FROM support_tickets WHERE status='open' ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return jsonify([_row_to_dict(row) for row in rows])
    except Exception as e:
        log.error("support-ticket: GET /tickets/open: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.put("/tickets/<int:tid>/close")
def close_ticket(tid):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE support_tickets SET status='closed' WHERE id=%s
                RETURNING id, user_id, subject, body, priority, status, created_at
                """,
                (tid,),
            ).fetchone()
            conn.commit()
        if not row:
            return jsonify({"error": "not found"}), 404
        try:
            r.srem(OPEN_TICKETS_KEY, str(tid))
        except Exception as e:
            log.error("support-ticket: cache srem: %s", e)
        return jsonify(_row_to_dict(row))
    except Exception as e:
        log.error("support-ticket: PUT /tickets/<id>/close: %s", e)
        return jsonify({"error": "internal error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
