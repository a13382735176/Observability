import logging, os, sys, json
import psycopg_pool, redis as syncredis
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("mention-service")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
STREAM_HOST = os.environ.get("REDIS_STREAM_HOST", "redis-stream")
STREAM_PORT = int(os.environ.get("REDIS_STREAM_PORT", "6379"))

pool = psycopg_pool.ConnectionPool(PG_DSN, min_size=1, max_size=5, timeout=2)
rstream = syncredis.Redis(host=STREAM_HOST, port=STREAM_PORT, socket_connect_timeout=2, decode_responses=True)

try:
    with pool.connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS mentions(id SERIAL PRIMARY KEY,"
                     "mentioned_user TEXT NOT NULL, content_id TEXT NOT NULL,"
                     "created_at TIMESTAMPTZ DEFAULT NOW())")
        conn.commit()
    log.info("db init ok")
except Exception as e:
    log.error("mention-service: db init failed: %s", e)

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "mention-service"})

@app.post("/mentions")
def create_mention():
    data = request.get_json(force=True)
    content = data.get("content", "")
    mentioned_users = data.get("mentioned_users", [])
    content_id = data.get("content_id", "unknown")
    try:
        with pool.connection() as conn:
            for user in mentioned_users:
                conn.execute("INSERT INTO mentions(mentioned_user,content_id) VALUES(%s,%s)", (user, content_id))
            conn.commit()
        payload = {"content_id": content_id, "mentioned_users": mentioned_users, "content": content}
        try:
            rstream.xadd("events:mentions", {"event": "mention.created", "payload": json.dumps(payload)})
        except Exception as e:
            log.error("mention-service: stream publish failed: %s", e)
        return jsonify(payload), 201
    except Exception as e:
        log.error("mention-service: POST /mentions: %s", e)
        return jsonify({"error": "internal error"}), 500

@app.get("/mentions/<user_id>")
def get_mentions(user_id):
    try:
        with pool.connection() as conn:
            rows = conn.execute("SELECT id,mentioned_user,content_id,created_at FROM mentions WHERE mentioned_user=%s ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()
        return jsonify([{"id": r[0], "mentioned_user": r[1], "content_id": r[2], "created_at": str(r[3])} for r in rows])
    except Exception as e:
        log.error("mention-service: GET /mentions/%s: %s", user_id, e)
        return jsonify({"error": "internal error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
