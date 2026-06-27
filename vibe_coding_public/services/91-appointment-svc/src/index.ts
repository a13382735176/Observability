import express, { Request, Response } from "express";
import { Pool } from "pg";
import { createClient } from "redis";

const app = express();
app.use(express.json());

const PG_DSN = process.env.PG_DSN || "postgres://vibe:vibe@postgres:5432/vibe";
const CACHE_HOST = process.env.REDIS_CACHE_HOST || "redis-cache";

const pg = new Pool({ connectionString: PG_DSN, connectionTimeoutMillis: 2000 });
const redis = createClient({ socket: { host: CACHE_HOST, port: 6379, connectTimeout: 2000 } });

redis.on("error", (err: Error) => console.error("ERROR appointment-svc:", err));
redis.connect().catch((err: Error) => console.error("ERROR appointment-svc:", err));

async function initDb() {
  try {
    await pg.query(`CREATE TABLE IF NOT EXISTS appointments(
      id serial PRIMARY KEY,
      patient_id text,
      doctor_id text,
      appointment_time timestamptz,
      reason text,
      status text DEFAULT 'booked'
    )`);
  } catch (err) {
    console.error("ERROR appointment-svc:", err);
  }
}

app.get("/healthz", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "appointment-svc" });
});

app.post("/appointments", async (req: Request, res: Response) => {
  const { patient_id, doctor_id, datetime_iso, reason } = req.body;
  try {
    const result = await pg.query(
      "INSERT INTO appointments(patient_id,doctor_id,appointment_time,reason) VALUES($1,$2,$3,$4) RETURNING id,patient_id,doctor_id,appointment_time,reason,status",
      [patient_id, doctor_id, datetime_iso, reason]
    );
    const row = result.rows[0];
    await redis.sAdd(`apts:${patient_id}`, String(row.id));
    res.status(201).json(row);
  } catch (err) {
    console.error("ERROR appointment-svc:", err);
    res.status(503).json({ error: "error" });
  }
});

app.get("/appointments/:patient_id", async (req: Request, res: Response) => {
  const { patient_id } = req.params;
  try {
    const ids = await redis.sMembers(`apts:${patient_id}`);
    if (ids.length === 0) {
      const r = await pg.query("SELECT id,patient_id,doctor_id,appointment_time,reason,status FROM appointments WHERE patient_id=$1", [patient_id]);
      return res.json(r.rows);
    }
    const placeholders = ids.map((_: string, i: number) => `$${i + 1}`).join(",");
    const r = await pg.query(`SELECT id,patient_id,doctor_id,appointment_time,reason,status FROM appointments WHERE id IN (${placeholders})`, ids.map(Number));
    res.json(r.rows);
  } catch (err) {
    console.error("ERROR appointment-svc:", err);
    res.status(503).json({ error: "error" });
  }
});

app.put("/appointments/:id/cancel", async (req: Request, res: Response) => {
  const id = parseInt(req.params.id);
  try {
    const result = await pg.query(
      "UPDATE appointments SET status='cancelled' WHERE id=$1 RETURNING id,patient_id,status",
      [id]
    );
    if (!result.rows.length) return res.status(404).json({ error: "not found" });
    res.json(result.rows[0]);
  } catch (err) {
    console.error("ERROR appointment-svc:", err);
    res.status(503).json({ error: "error" });
  }
});

initDb().then(() => {
  app.listen(8080, "0.0.0.0", () => console.log("appointment-svc listening on 8080"));
});
