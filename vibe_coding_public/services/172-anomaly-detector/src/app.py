import logging
import math
import os
import sys

import psycopg_pool
import redis
from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("anomaly-detector")

SERVICE = "anomaly-detector"
PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_STREAM_HOST = os.environ.get("REDIS_STREAM_HOST", "redis-stream")
REDIS_STREAM_PORT = int(os.environ.get("REDIS_STREAM_PORT", "6379"))
STREAM_KEY = "events:anomalies"
Z_THRESHOLD = 3.0
MIN_SAMPLES_FOR_DETECTION = 10

pool = psycopg_pool.ConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, kwargs={"connect_timeout": 2}
)

r = redis.Redis(
    host=REDIS_STREAM_HOST,
    port=REDIS_STREAM_PORT,
    socket_timeout=2,
    socket_connect_timeout=2,
    decode_responses=True,
)

DDL = [
    """
    CREATE TABLE IF NOT EXISTS data_samples(
        id bigserial PRIMARY KEY,
        metric text,
        value double precision,
        created_at timestamptz DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS anomalies(
        id bigserial PRIMARY KEY,
        metric text,
        value double precision,
        z_score double precision,
        detected_at timestamptz DEFAULT now()
    )
    """,
]

try:
    with pool.connection() as conn:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    log.info("anomaly-detector: db init ok")
except Exception as e:
    log.error("anomaly-detector: db init: %s", e)

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": SERVICE})


@app.post("/samples")
def add_sample():
    body = request.get_json(silent=True) or {}
    metric = body.get("metric")
    value = body.get("value")
    if not metric or value is None:
        return jsonify({"error": "metric, value required"}), 400
    try:
        value = float(value)
    except (TypeError, ValueError):
        return jsonify({"error": "value must be a number"}), 400

    try:
        with pool.connection() as conn:
            sample_id = conn.execute(
                "INSERT INTO data_samples(metric, value) VALUES (%s, %s) RETURNING id",
                (metric, value),
            ).fetchone()[0]

            row = conn.execute(
                """
                SELECT AVG(value), STDDEV(value), COUNT(*)
                FROM data_samples
                WHERE metric=%s AND created_at > now() - interval '1 hour'
                """,
                (metric,),
            ).fetchone()
            conn.commit()
    except Exception as e:
        log.error("anomaly-detector: POST /samples: %s", e)
        return jsonify({"error": "internal error"}), 500

    avg, stddev, count = row or (None, None, 0)
    is_anomaly = False
    z_score = None
    if count and count > MIN_SAMPLES_FOR_DETECTION and stddev and stddev > 0:
        z_score = abs(value - float(avg)) / float(stddev)
        if z_score > Z_THRESHOLD and not (math.isnan(z_score) or math.isinf(z_score)):
            is_anomaly = True
            try:
                with pool.connection() as conn:
                    conn.execute(
                        "INSERT INTO anomalies(metric, value, z_score) VALUES (%s, %s, %s)",
                        (metric, value, z_score),
                    )
                    conn.commit()
            except Exception as e:
                log.error("anomaly-detector: insert anomaly: %s", e)
            try:
                r.xadd(
                    STREAM_KEY,
                    {"metric": metric, "value": str(value), "z_score": f"{z_score:.4f}"},
                )
            except Exception as e:
                log.error("anomaly-detector: XADD events:anomalies: %s", e)

    return jsonify(
        {
            "id": sample_id,
            "metric": metric,
            "value": value,
            "is_anomaly": is_anomaly,
            "z_score": z_score,
            "rolling_count": int(count or 0),
        }
    ), 201


@app.get("/anomalies")
def list_anomalies():
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, metric, value, z_score, detected_at
                FROM anomalies
                ORDER BY detected_at DESC
                LIMIT 50
                """
            ).fetchall()
        return jsonify(
            [
                {
                    "id": row[0],
                    "metric": row[1],
                    "value": row[2],
                    "z_score": row[3],
                    "detected_at": row[4].isoformat() if row[4] else None,
                }
                for row in rows
            ]
        )
    except Exception as e:
        log.error("anomaly-detector: GET /anomalies: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/samples/<metric>/stats")
def metric_stats(metric):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                SELECT AVG(value), STDDEV(value), COUNT(*)
                FROM data_samples
                WHERE metric=%s AND created_at > now() - interval '1 hour'
                """,
                (metric,),
            ).fetchone()
        avg, stddev, count = row or (None, None, 0)
        return jsonify(
            {
                "metric": metric,
                "avg": float(avg) if avg is not None else None,
                "stddev": float(stddev) if stddev is not None else None,
                "count": int(count or 0),
            }
        )
    except Exception as e:
        log.error("anomaly-detector: GET /samples/<metric>/stats: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/samples/<metric>/recent")
def recent_samples(metric):
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, metric, value, created_at
                FROM data_samples
                WHERE metric=%s
                ORDER BY id DESC
                LIMIT 100
                """,
                (metric,),
            ).fetchall()
        return jsonify(
            [
                {
                    "id": row[0],
                    "metric": row[1],
                    "value": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                }
                for row in rows
            ]
        )
    except Exception as e:
        log.error("anomaly-detector: GET /samples/<metric>/recent: %s", e)
        return jsonify({"error": "internal error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
