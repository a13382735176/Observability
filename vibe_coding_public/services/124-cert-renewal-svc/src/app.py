import logging, os, sys
import psycopg_pool
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s :: %(message)s", stream=sys.stdout)
log = logging.getLogger("cert-renewal-svc")

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")

pool = psycopg_pool.ConnectionPool(PG_DSN, min_size=1, max_size=4, timeout=2, kwargs={"connect_timeout": 2})

try:
    with pool.connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS certificates("
            "id SERIAL PRIMARY KEY,"
            "domain TEXT UNIQUE NOT NULL,"
            "expiry_date DATE NOT NULL,"
            "issuer TEXT,"
            "last_renewed_at TIMESTAMPTZ)"
        )
        conn.commit()
    log.info("db init ok")
except Exception as e:
    log.error("cert-renewal-svc: db init failed: %s", e)

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "cert-renewal-svc"})


@app.post("/certs")
def upsert_cert():
    data = request.get_json(force=True) or {}
    domain = data.get("domain")
    expiry_date = data.get("expiry_date")
    issuer = data.get("issuer")
    if not domain or not expiry_date:
        return jsonify({"error": "domain and expiry_date required"}), 400
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO certificates(domain,expiry_date,issuer) VALUES(%s,%s,%s) "
                "ON CONFLICT(domain) DO UPDATE SET expiry_date=EXCLUDED.expiry_date, issuer=EXCLUDED.issuer "
                "RETURNING id,domain,expiry_date,issuer,last_renewed_at",
                (domain, expiry_date, issuer),
            ).fetchone()
            conn.commit()
        return jsonify({
            "id": row[0], "domain": row[1], "expiry_date": str(row[2]),
            "issuer": row[3], "last_renewed_at": str(row[4]) if row[4] else None,
        }), 201
    except Exception as e:
        log.error("cert-renewal-svc: POST /certs: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/certs/expiring")
def expiring_certs():
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id,domain,expiry_date,issuer,last_renewed_at FROM certificates "
                "WHERE expiry_date < CURRENT_DATE + interval '30 days' "
                "ORDER BY expiry_date ASC"
            ).fetchall()
        return jsonify([
            {"id": r[0], "domain": r[1], "expiry_date": str(r[2]), "issuer": r[3],
             "last_renewed_at": str(r[4]) if r[4] else None}
            for r in rows
        ])
    except Exception as e:
        log.error("cert-renewal-svc: GET /certs/expiring: %s", e)
        return jsonify({"error": "internal error"}), 500


@app.get("/certs/<domain>")
def get_cert(domain):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT id,domain,expiry_date,issuer,last_renewed_at FROM certificates WHERE domain=%s",
                (domain,),
            ).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "id": row[0], "domain": row[1], "expiry_date": str(row[2]),
            "issuer": row[3], "last_renewed_at": str(row[4]) if row[4] else None,
        })
    except Exception as e:
        log.error("cert-renewal-svc: GET /certs/%s: %s", domain, e)
        return jsonify({"error": "internal error"}), 500


@app.post("/certs/<int:cert_id>/renew")
def renew_cert(cert_id):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "UPDATE certificates SET expiry_date = expiry_date + interval '365 days', "
                "last_renewed_at = now() WHERE id=%s "
                "RETURNING id,domain,expiry_date,issuer,last_renewed_at",
                (cert_id,),
            ).fetchone()
            conn.commit()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "id": row[0], "domain": row[1], "expiry_date": str(row[2]),
            "issuer": row[3], "last_renewed_at": str(row[4]) if row[4] else None,
        })
    except Exception as e:
        log.error("cert-renewal-svc: POST /certs/%s/renew: %s", cert_id, e)
        return jsonify({"error": "internal error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
