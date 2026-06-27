import logging, os
from flask import Flask, jsonify, request
import psycopg_pool

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

PG_DSN = os.environ.get("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
pool = psycopg_pool.ConnectionPool(PG_DSN, min_size=1, max_size=5, timeout=2.0, open=False)
pool.open()

def init_db():
    try:
        with pool.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tax_reports(
                    id serial PRIMARY KEY,
                    user_id text,
                    tax_year int,
                    income_cents bigint,
                    deductions_cents bigint,
                    taxable_cents bigint,
                    created_at timestamptz DEFAULT now()
                )""")
            conn.commit()
    except Exception as e:
        app.logger.error("tax-reporting: %s", e)

init_db()

COLS = ["id","user_id","tax_year","income_cents","deductions_cents","taxable_cents","created_at"]

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "tax-reporting"})

@app.post("/reports")
def create_report():
    data = request.get_json(force=True)
    try:
        user_id = data["user_id"]
        tax_year = int(data["tax_year"])
        income = int(data["income_cents"])
        deductions = int(data["deductions_cents"])
        taxable = income - deductions
        with pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO tax_reports(user_id,tax_year,income_cents,deductions_cents,taxable_cents)"
                " VALUES(%s,%s,%s,%s,%s) RETURNING id,user_id,tax_year,income_cents,deductions_cents,taxable_cents,created_at::text",
                (user_id, tax_year, income, deductions, taxable)
            ).fetchone()
            conn.commit()
        return jsonify(dict(zip(COLS, row))), 201
    except Exception as e:
        app.logger.error("tax-reporting: %s", e)
        return jsonify({"error": "db error"}), 503

@app.get("/reports/<user_id>")
def get_by_user(user_id):
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT id,user_id,tax_year,income_cents,deductions_cents,taxable_cents,created_at::text"
                " FROM tax_reports WHERE user_id=%s",
                (user_id,)
            ).fetchall()
        return jsonify([dict(zip(COLS, r)) for r in rows])
    except Exception as e:
        app.logger.error("tax-reporting: %s", e)
        return jsonify({"error": "db error"}), 503

@app.get("/report/<int:rid>")
def get_by_id(rid):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT id,user_id,tax_year,income_cents,deductions_cents,taxable_cents,created_at::text"
                " FROM tax_reports WHERE id=%s",
                (rid,)
            ).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(zip(COLS, row)))
    except Exception as e:
        app.logger.error("tax-reporting: %s", e)
        return jsonify({"error": "db error"}), 503

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
