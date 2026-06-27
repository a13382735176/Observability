import logging, os, sys
import psycopg_pool
import redis
from flask import Flask, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("backup-orchestrator")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
REDIS_STREAM_HOST = os.environ.get("REDIS_STREAM_HOST", "redis-stream")
REDIS_STREAM_PORT = int(os.environ.get("REDIS_STREAM_PORT", "6379"))

pool = psycopg_pool.ConnectionPool(
    PG_DSN, min_size=1, max_size=4, timeout=2, kwargs={"connect_timeout": 2}
)

stream = redis.Redis(
    host=REDIS_STREAM_HOST,
    port=REDIS_STREAM_PORT,
    socket_timeout=2,
    socket_connect_timeout=2,
)

try:
    with pool.connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS backup_records("
            "id BIGSERIAL PRIMARY KEY,"
            "resource_type TEXT NOT NULL,"
            "resource_id TEXT NOT NULL,"
            "location TEXT NOT NULL,"
            "size_bytes BIGINT,"
            "created_at TIMESTAMPTZ DEFAULT now())"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS restore_jobs("
            "id BIGSERIAL PRIMARY KEY,"
            "backup_id BIGINT NOT NULL,"
            "status TEXT DEFAULT 'pending',"
            "requested_at TIMESTAMPTZ DEFAULT now(),"
            "completed_at TIMESTAMPTZ)"
        )
        conn.commit()
    log.info("db init ok")
except Exception as e:
    log.error("backup-orchestrator: db init failed: %s", e)

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "backup-orchestrator"})


@app.post("/backups")
def create_backup():
    data = request.get_json(force=True) or {}
    resource_type = data.get("resource_type")
    resource_id = data.get("resource_id")
    location = data.get("location")
    size_bytes = data.get("size_bytes")
    if not resource_type or not resource_id or not location:
        return jsonify({"error": "resource_type, resource_id, location required"}), 400
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO backup_records(resource_type,resource_id,location,size_bytes) "
                "VALUES(%s,%s,%s,%s) "
                "RETURNING id,resource_type,resource_id,location,size_bytes,created_at",
                (resource_type, resource_id, location, size_bytes),
            ).fetchone()
            conn.commit()
        record = {
            "id": row[0],
            "resource_type": row[1],
            "resource_id": row[2],
            "location": row[3],
            "size_bytes": row[4],
            "created_at": str(row[5]),
        }
        try:
            stream.xadd(
                "events:backups",
                {
                    "id": str(record["id"]),
                    "resource_type": record["resource_type"],
                    "resource_id": record["resource_id"],
                },
            )
        except Exception as xe:
            log.error("backup-orchestrator: xadd events:backups: %s", xe)
        return jsonify(record), 201
    except Exception as e:
        log.error("backup-orchestrator: POST /backups: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/backups")
def list_backups():
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id,resource_type,resource_id,location,size_bytes,created_at "
                "FROM backup_records ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return jsonify(
            [
                {
                    "id": r[0],
                    "resource_type": r[1],
                    "resource_id": r[2],
                    "location": r[3],
                    "size_bytes": r[4],
                    "created_at": str(r[5]),
                }
                for r in rows
            ]
        )
    except Exception as e:
        log.error("backup-orchestrator: GET /backups: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/backups/<resource_type>/<resource_id>")
def get_backups_for_resource(resource_type, resource_id):
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id,resource_type,resource_id,location,size_bytes,created_at "
                "FROM backup_records WHERE resource_type=%s AND resource_id=%s "
                "ORDER BY created_at DESC",
                (resource_type, resource_id),
            ).fetchall()
        return jsonify(
            [
                {
                    "id": r[0],
                    "resource_type": r[1],
                    "resource_id": r[2],
                    "location": r[3],
                    "size_bytes": r[4],
                    "created_at": str(r[5]),
                }
                for r in rows
            ]
        )
    except Exception as e:
        log.error(
            "backup-orchestrator: GET /backups/%s/%s: %s",
            resource_type,
            resource_id,
            e,
        )
        return jsonify({"error": "internal error"}), 500


@app.post("/restore")
def create_restore():
    data = request.get_json(force=True) or {}
    backup_id = data.get("backup_id")
    if backup_id is None:
        return jsonify({"error": "backup_id required"}), 400
    try:
        with pool.connection() as conn:
            backup = conn.execute(
                "SELECT id FROM backup_records WHERE id=%s", (backup_id,)
            ).fetchone()
            if not backup:
                return jsonify({"error": "backup not found"}), 404
            row = conn.execute(
                "INSERT INTO restore_jobs(backup_id) VALUES(%s) "
                "RETURNING id,backup_id,status,requested_at",
                (backup_id,),
            ).fetchone()
            conn.commit()
        result = {
            "restore_job_id": row[0],
            "backup_id": row[1],
            "status": row[2],
            "requested_at": str(row[3]),
        }
        try:
            stream.xadd(
                "events:restores",
                {
                    "restore_job_id": str(result["restore_job_id"]),
                    "backup_id": str(result["backup_id"]),
                    "status": result["status"],
                },
            )
        except Exception as xe:
            log.error("backup-orchestrator: xadd events:restores: %s", xe)
        return jsonify(result), 201
    except Exception as e:
        log.error("backup-orchestrator: POST /restore: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.put("/restore/<int:restore_id>/complete")
def complete_restore(restore_id):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "UPDATE restore_jobs SET status='completed', completed_at=now() "
                "WHERE id=%s "
                "RETURNING id,backup_id,status,requested_at,completed_at",
                (restore_id,),
            ).fetchone()
            conn.commit()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(
            {
                "id": row[0],
                "backup_id": row[1],
                "status": row[2],
                "requested_at": str(row[3]),
                "completed_at": str(row[4]) if row[4] else None,
            }
        )
    except Exception as e:
        log.error(
            "backup-orchestrator: PUT /restore/%s/complete: %s", restore_id, e
        )
        return jsonify({"error": "internal error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
