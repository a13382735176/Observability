import express, { Request, Response } from "express";
import Redis from "ioredis";

const app = express();
app.use(express.json());

const STREAM_HOST = process.env.REDIS_STREAM_HOST || "redis-stream";
let redis: Redis;
let msgCount = 0;

function getRedis(): Redis {
  if (!redis) {
    redis = new Redis({ host: STREAM_HOST, port: 6379, connectTimeout: 2000, commandTimeout: 2000 });
    redis.on("error", (e: Error) => console.error(`batch-reader: ${e.message}`));
  }
  return redis;
}

app.get("/healthz", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "batch-reader" });
});

app.get("/stats", (_req: Request, res: Response) => {
  res.json({ messages_read: msgCount });
});

app.post("/read", async (req: Request, res: Response) => {
  const count: number = req.body?.count ?? 10;
  try {
    const r = getRedis();
    const results = await r.xread("COUNT", count, "STREAMS", "events:telemetry", "0-0");
    const messages: any[] = [];
    if (results) {
      for (const [, entries] of results as any[]) {
        for (const [id, fields] of entries) {
          msgCount++;
          messages.push({ id, fields });
        }
      }
    }
    res.json({ count: messages.length, messages });
  } catch (e: any) {
    console.error(`batch-reader: ${e.message}`);
    res.status(503).json({ error: "redis error" });
  }
});

app.listen(8080, "0.0.0.0", () => console.log("batch-reader listening on 8080"));
