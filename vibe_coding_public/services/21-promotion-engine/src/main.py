import logging, os, sys
import psycopg
import redis as redis_sync
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("promotion-engine")

app = Flask(__name__)

def get_pg():
    return psycopg.connect(
        os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe"),
        connect_timeout=2)

def get_redis():
    return redis_sync.Redis(
        host=os.environ.get("REDIS_CACHE_HOST", "redis-cache"),
        port=int(os.environ.get("REDIS_CACHE_PORT", "6379")),
        socket_connect_timeout=2, decode_responses=True)

def init_db():
    try:
        with get_pg() as conn:
            conn.execute(
                'CREATE TABLE IF NOT EXISTS promotions ('
                '    id SERIAL PRIMARY KEY,'
                '    code TEXT UNIQUE NOT NULL,'
                '    discount_pct INT NOT NULL,'
                '    active BOOL DEFAULT TRUE'
                ')'
            )
            conn.commit()
        log.info("postgres ready")
    except Exception as e:
        log.error("postgres init failed: %s", e)

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "promotion-engine"})

@app.get("/promotions")
def get_promotions():
    try:
        with get_pg() as conn:
            rows = conn.execute("SELECT id,code,discount_pct,active FROM promotions ORDER BY id").fetchall()
            return jsonify([{"id":r[0],"code":r[1],"discount_pct":r[2],"active":r[3]} for r in rows])
    except Exception as e:
        log.error("GET /promotions failed: %s", e)
        return jsonify({"error": "internal error"}), 500

@app.post("/promotions")
def create_promotion():
    data = request.get_json() or {}
    code, pct = data.get("code"), data.get("discount_pct")
    try:
        with get_pg() as conn:
            row = conn.execute(
                "INSERT INTO promotions(code,discount_pct) VALUES(%s,%s) RETURNING id,code,discount_pct,active",
                (code, pct)).fetchone()
            conn.commit()
            return jsonify({"id":row[0],"code":row[1],"discount_pct":row[2],"active":row[3]}), 201
    except Exception as e:
        log.error("POST /promotions failed: %s", e)
        return jsonify({"error": "internal error"}), 500

@app.get("/validate/<code>")
def validate(code):
    try:
        rdb = get_redis()
        cached = rdb.get(f"promo:{code}")
        if cached:
            return jsonify({"code": code, "discount_pct": int(cached), "valid": True})
    except Exception as e:
        log.error("redis get promo:%s failed: %s", code, e)
    try:
        with get_pg() as conn:
            row = conn.execute(
                "SELECT discount_pct FROM promotions WHERE code=%s AND active=true", (code,)).fetchone()
            if not row:
                return jsonify({"valid": False}), 404
            try:
                rdb.setex(f"promo:{code}", 300, row[0])
            except Exception as e:
                log.error("redis set promo:%s failed: %s", code, e)
            return jsonify({"code": code, "discount_pct": row[0], "valid": True})
    except Exception as e:
        log.error("GET /validate/%s failed: %s", code, e)
        return jsonify({"error": "internal error"}), 500

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)
