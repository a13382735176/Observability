import express, { Request, Response } from "express";
import Redis from "ioredis";

const app = express();
app.use(express.json());

const CACHE_HOST = process.env.REDIS_CACHE_HOST || "redis-cache";
const UPSTREAM = "http://mock-upstream:8080";

let redis: Redis;

function getRedis(): Redis {
  if (!redis) {
    redis = new Redis({ host: CACHE_HOST, port: 6379, connectTimeout: 2000, commandTimeout: 2000 });
    redis.on("error", (e: Error) => console.error(`fx-rate-service: ${e.message}`));
  }
  return redis;
}

app.get("/healthz", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "fx-rate-service" });
});

app.get("/rates", async (_req: Request, res: Response) => {
  try {
    const r = getRedis();
    const all = await r.hgetall("fx:rates");
    const rates = Object.entries(all || {}).map(([pair, rate]) => ({ pair, rate: parseFloat(rate) }));
    res.json({ rates });
  } catch (e: any) {
    console.error(`fx-rate-service: ${e.message}`);
    res.status(503).json({ error: "redis error" });
  }
});

app.get("/rates/:pair", async (req: Request, res: Response) => {
  try {
    const r = getRedis();
    const rate = await r.hget("fx:rates", req.params.pair);
    if (!rate) return res.status(404).json({ error: "not found" }) as any;
    res.json({ pair: req.params.pair, rate: parseFloat(rate) });
  } catch (e: any) {
    console.error(`fx-rate-service: ${e.message}`);
    res.status(503).json({ error: "redis error" });
  }
});

app.post("/refresh", async (_req: Request, res: Response) => {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    const resp = await fetch(`${UPSTREAM}/rates`, { signal: controller.signal });
    clearTimeout(timeout);
    if (!resp.ok) throw new Error(`upstream ${resp.status}`);
    const data = await resp.json() as any;
    const r = getRedis();
    const pipeline = r.pipeline();
    const rates: Record<string, number> = data.rates || { USDEUR: 0.92, USDJPY: 155.0, USDGBP: 0.79 };
    for (const [pair, rate] of Object.entries(rates)) {
      pipeline.hset("fx:rates", pair, String(rate));
    }
    await pipeline.exec();
    await r.expire("fx:rates", 60);
    res.json({ ok: true, count: Object.keys(rates).length });
  } catch (e: any) {
    console.error(`fx-rate-service: upstream: ${e.message}`);
    // Store fallback rates
    try {
      const r = getRedis();
      await r.hset("fx:rates", "USDEUR", "0.92", "USDJPY", "155.0");
      await r.expire("fx:rates", 60);
    } catch (_) {}
    res.status(503).json({ error: "upstream error", message: e.message });
  }
});

app.listen(8080, "0.0.0.0", () => console.log("fx-rate-service listening on 8080"));
