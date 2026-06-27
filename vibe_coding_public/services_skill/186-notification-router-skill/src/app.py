import json
import logging
import os
import time
from contextlib import closing
from typing import Any, Dict

import psycopg
import redis
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

APP_NAME = os.getenv("APP_NAME", "notification-router-skill")
PG_DSN = os.getenv("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_CACHE_HOST = os.getenv("REDIS_CACHE_HOST", "redis-cache")
REDIS_CACHE_PORT = int(os.getenv("REDIS_CACHE_PORT", "6379"))

SCHEMA_SQL = (
    "CREATE TABLE IF NOT EXISTS user_channels( id bigserial PRIMARY KEY, user_id text, channel_type text, target text, created_at timestamptz DEFAULT now() )",
    "CREATE TABLE IF NOT EXISTS routed_notifications( id bigserial PRIMARY KEY, user_id text, channel_type text, message text, priority int DEFAULT 3, sent_at timestamptz DEFAULT now() )",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event: Dict[str, Any] = {
            "service": APP_NAME,
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for key in ("operation", "dependency", "status", "latency_ms", "error_type", "request_id"):
            value = getattr(record, key, None)
            if value is not None:
                event[key] = value
        if record.exc_info:
            event["error_type"] = event.get("error_type") or record.exc_info[0].__name__
        return json.dumps(event, separators=(",", ":"))


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[handler], force=True)
logger = logging.getLogger(APP_NAME)

app = Flask(__name__)
_schema_ready = False


def _request_id() -> str | None:
    return request.headers.get("X-Request-Id") or request.headers.get("X-Correlation-Id")


def redis_client() -> redis.Redis:
    return redis.Redis(host=REDIS_CACHE_HOST, port=REDIS_CACHE_PORT, socket_timeout=1.0, socket_connect_timeout=1.0)


def ensure_schema() -> bool:
    global _schema_ready
    if _schema_ready:
        return True
    start = time.monotonic()
    try:
        with closing(psycopg.connect(PG_DSN, connect_timeout=2)) as conn:
            with conn.cursor() as cur:
                for statement in SCHEMA_SQL:
                    cur.execute(statement)
            conn.commit()
        _schema_ready = True
        logger.info(
            "postgres schema ready",
            extra={"operation": "schema_init", "dependency": "postgres", "status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 2)},
        )
        return True
    except Exception as exc:
        logger.warning(
            "postgres schema unavailable",
            extra={
                "operation": "schema_init",
                "dependency": "postgres",
                "status": "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        return False


def check_redis() -> bool:
    start = time.monotonic()
    try:
        redis_client().ping()
        logger.info(
            "redis cache ready",
            extra={"operation": "dependency_check", "dependency": "redis-cache", "status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 2)},
        )
        return True
    except Exception as exc:
        logger.warning(
            "redis cache unavailable",
            extra={
                "operation": "dependency_check",
                "dependency": "redis-cache",
                "status": "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        return False


@app.before_request
def log_request_start() -> None:
    request._started_at = time.monotonic()  # type: ignore[attr-defined]


@app.after_request
def log_request_end(response):
    started_at = getattr(request, "_started_at", time.monotonic())
    logger.info(
        "request completed",
        extra={
            "operation": f"{request.method} {request.path}",
            "status": response.status_code,
            "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            "request_id": _request_id(),
        },
    )
    return response


@app.errorhandler(Exception)
def handle_error(exc: Exception):
    if isinstance(exc, HTTPException):
        return exc
    logger.exception(
        "request failed",
        extra={"operation": f"{request.method} {request.path}", "status": 500, "error_type": type(exc).__name__, "request_id": _request_id()},
    )
    return jsonify({"error": "internal_error"}), 500


@app.get("/healthz")
def healthz():
    postgres_ok = ensure_schema()
    redis_ok = check_redis()
    status = "ok" if postgres_ok and redis_ok else "degraded"
    return jsonify({"service": APP_NAME, "status": status, "postgres": postgres_ok, "redis_cache": redis_ok}), 200


# Best-effort startup preparation. The process remains runnable if dependencies are
# not yet available; readiness reports degraded until checks succeed.
with app.app_context():
    logger.info("service starting", extra={"operation": "startup", "status": "starting"})
    ensure_schema()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
