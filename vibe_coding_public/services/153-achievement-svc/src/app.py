import json
import logging
import os
import sys

import redis
from flask import Flask, jsonify, request
from psycopg_pool import ConnectionPool

SERVICE = "achievement-svc"
PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis-cache:6379")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(SERVICE)

pool = ConnectionPool(
    PG_DSN,
    min_size=1,
    max_size=4,
    timeout=2,
    kwargs={"connect_timeout": 2},
)

r = redis.Redis.from_url(
    REDIS_URL,
    socket_timeout=2,
    socket_connect_timeout=2,
    decode_responses=True,
)

DDL = """
CREATE TABLE IF NOT EXISTS achievement_defs (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    points INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS user_achievements (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    achievement_code TEXT NOT NULL,
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, achievement_code)
);
"""

try:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
except Exception as e:  # noqa: BLE001
    log.error("%s: bootstrap DDL failed: %s", SERVICE, e)

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": SERVICE})


@app.post("/achievements")
def define_achievement():
    body = request.get_json(silent=True) or {}
    code = body.get("code")
    name = body.get("name")
    if not code or not name:
        return jsonify({"error": "code and name required"}), 400
    description = body.get("description", "")
    points = int(body.get("points", 0))
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO achievement_defs (code, name, description, points)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE
                      SET name = EXCLUDED.name,
                          description = EXCLUDED.description,
                          points = EXCLUDED.points
                    RETURNING id, code, name, description, points
                    """,
                    (code, name, description, points),
                )
                row = cur.fetchone()
            conn.commit()
        return jsonify(
            {
                "id": row[0],
                "code": row[1],
                "name": row[2],
                "description": row[3],
                "points": row[4],
            }
        )
    except Exception as e:  # noqa: BLE001
        log.error("%s: define %s: %s", SERVICE, code, e)
        return jsonify({"error": "db error"}), 500


@app.get("/achievements")
def list_achievements():
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, name, description, points FROM achievement_defs ORDER BY code"
                )
                rows = cur.fetchall()
        return jsonify(
            [
                {"code": c, "name": n, "description": d, "points": p}
                for (c, n, d, p) in rows
            ]
        )
    except Exception as e:  # noqa: BLE001
        log.error("%s: list defs: %s", SERVICE, e)
        return jsonify({"error": "db error"}), 500


@app.post("/unlock")
def unlock():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    code = body.get("achievement_code")
    if not user_id or not code:
        return jsonify({"error": "user_id and achievement_code required"}), 400
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_achievements (user_id, achievement_code)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id, achievement_code) DO NOTHING
                    RETURNING id, unlocked_at
                    """,
                    (user_id, code),
                )
                row = cur.fetchone()
            conn.commit()
        cache_key = f"ach:{user_id}"
        try:
            r.sadd(cache_key, code)
        except Exception as ce:  # noqa: BLE001
            log.error("%s: SADD %s: %s", SERVICE, cache_key, ce)
        return jsonify(
            {
                "user_id": user_id,
                "achievement_code": code,
                "newly_unlocked": row is not None,
            }
        )
    except Exception as e:  # noqa: BLE001
        log.error("%s: unlock %s/%s: %s", SERVICE, user_id, code, e)
        return jsonify({"error": "db error"}), 500


@app.get("/achievements/<user_id>")
def user_achievements(user_id: str):
    cache_key = f"ach:{user_id}"
    try:
        cached = r.smembers(cache_key)
    except Exception as ce:  # noqa: BLE001
        log.error("%s: SMEMBERS %s: %s", SERVICE, cache_key, ce)
        cached = set()
    if cached:
        return jsonify({"user_id": user_id, "source": "cache", "codes": sorted(cached)})
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT achievement_code FROM user_achievements WHERE user_id = %s",
                    (user_id,),
                )
                codes = [row[0] for row in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        log.error("%s: list user %s: %s", SERVICE, user_id, e)
        return jsonify({"error": "db error"}), 500
    if codes:
        try:
            r.sadd(cache_key, *codes)
        except Exception as ce:  # noqa: BLE001
            log.error("%s: repopulate %s: %s", SERVICE, cache_key, ce)
    return jsonify({"user_id": user_id, "source": "db", "codes": codes})
