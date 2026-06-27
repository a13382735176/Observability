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
log = logging.getLogger("notification-router")

SERVICE = "notification-router"
PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.environ.get("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.environ.get("REDIS_CACHE_PORT", "6379"))

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

DDL_CHANNELS = """
CREATE TABLE IF NOT EXISTS user_channels(
    id bigserial PRIMARY KEY,
    user_id text,
    channel_type text,
    target text,
    created_at timestamptz DEFAULT now()
)
"""

DDL_ROUTED = """
CREATE TABLE IF NOT EXISTS routed_notifications(
    id bigserial PRIMARY KEY,
    user_id text,
    channel_type text,
    message text,
    priority int DEFAULT 3,
    sent_at timestamptz DEFAULT now()
)
"""

try:
    with pool.connection() as conn:
        conn.execute(DDL_CHANNELS)
        conn.execute(DDL_ROUTED)
        conn.commit()
    log.info("notification-router: db init ok")
except Exception as e:
    log.error("notification-router: %s", e)

app = Flask(__name__)


def _ch_row(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "channel_type": row[2],
        "target": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
    }


def _notif_row(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "channel_type": row[2],
        "message": row[3],
        "priority": row[4],
        "sent_at": row[5].isoformat() if row[5] else None,
    }


def _channel_set_key(user_id):
    return f"ch:{user_id}"


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": SERVICE})


@app.post("/channels")
def add_channel():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    channel_type = body.get("channel_type")
    target = body.get("target")
    if not user_id or not channel_type or not target:
        return jsonify({"error": "user_id, channel_type, target required"}), 400
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO user_channels(user_id, channel_type, target)
                VALUES (%s, %s, %s)
                RETURNING id, user_id, channel_type, target, created_at
                """,
                (user_id, channel_type, target),
            ).fetchone()
            conn.commit()
        ch = _ch_row(row)
        try:
            r.sadd(_channel_set_key(user_id), f"{channel_type}|{target}")
        except Exception as e:
            log.error("notification-router: %s", e)
        return jsonify(ch), 201
    except Exception as e:
        log.error("notification-router: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/channels/<user_id>")
def list_channels(user_id):
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, user_id, channel_type, target, created_at FROM user_channels WHERE user_id=%s ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        return jsonify([_ch_row(row) for row in rows])
    except Exception as e:
        log.error("notification-router: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.delete("/channels/<int:cid>")
def delete_channel(cid):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT user_id, channel_type, target FROM user_channels WHERE id=%s",
                (cid,),
            ).fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404
            user_id, channel_type, target = row
            conn.execute("DELETE FROM user_channels WHERE id=%s", (cid,))
            conn.commit()
        try:
            r.srem(_channel_set_key(user_id), f"{channel_type}|{target}")
        except Exception as e:
            log.error("notification-router: %s", e)
        return jsonify({"deleted": cid})
    except Exception as e:
        log.error("notification-router: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.post("/route")
def route():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    message = body.get("message")
    priority = body.get("priority", 3)
    if not user_id or message is None:
        return jsonify({"error": "user_id, message required"}), 400

    channels = []
    used_cache = False
    try:
        members = r.smembers(_channel_set_key(user_id))
        if members:
            used_cache = True
            for m in members:
                if "|" in m:
                    ct, tgt = m.split("|", 1)
                    channels.append((ct, tgt))
    except Exception as e:
        log.error("notification-router: %s", e)

    if not channels:
        try:
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT channel_type, target FROM user_channels WHERE user_id=%s",
                    (user_id,),
                ).fetchall()
            channels = [(row[0], row[1]) for row in rows]
        except Exception as e:
            log.error("notification-router: %s", e)
            return jsonify({"error": "internal error"}), 500

    if not channels:
        return jsonify({"user_id": user_id, "routed_to": [], "source": "db"}), 200

    routed_to = []
    try:
        with pool.connection() as conn:
            for ct, tgt in channels:
                conn.execute(
                    """
                    INSERT INTO routed_notifications(user_id, channel_type, message, priority)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (user_id, ct, message, priority),
                )
                routed_to.append({"channel_type": ct, "target": tgt})
            conn.commit()
    except Exception as e:
        log.error("notification-router: %s", e)
        return jsonify({"error": "internal error"}), 500

    return jsonify({
        "user_id": user_id,
        "routed_to": routed_to,
        "source": "cache" if used_cache else "db",
    }), 200


@app.get("/notifications/<user_id>")
def list_notifications(user_id):
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, channel_type, message, priority, sent_at
                FROM routed_notifications
                WHERE user_id=%s
                ORDER BY id DESC LIMIT 50
                """,
                (user_id,),
            ).fetchall()
        return jsonify([_notif_row(row) for row in rows])
    except Exception as e:
        log.error("notification-router: %s", e)
        return jsonify({"error": "internal error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
