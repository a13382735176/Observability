# 180-order-history

TypeScript / Express service that records orders in Postgres and maintains a per-user
order history sorted by creation time in Redis (sorted set + per-order cache).

## Stack
- Node 20 (`node:20-alpine`), Express 4, `pg` 8, `redis` 4
- TypeScript executed via `ts-node`

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"order-history"}`
- `POST /orders` — body `{user_id, total_cents:int, item_count:int}` → INSERT, `ZADD user_orders:<user_id>` by `created_at_ms`, `SET order:<id> EX 3600`
- `GET /orders/:id` — Redis GET `order:<id>`; on miss Postgres SELECT + `SETEX 3600`
- `GET /orders/user/:user_id` — `ZREVRANGE user_orders:<user_id> 0 19` → `MGET order:<id>`; Postgres fallback if any missing
- `GET /orders/user/:user_id/recent?n=10` — same as above with configurable `n`
- `DELETE /orders/:id` — Postgres delete + `DEL order:<id>` + `ZREM user_orders:<user_id>`

## Schema (auto-created on startup)
```sql
CREATE TABLE IF NOT EXISTS order_history(
  id bigserial PRIMARY KEY,
  user_id text,
  total_cents bigint,
  item_count int,
  created_at timestamptz DEFAULT now()
);
```

## Logging / timeouts
- All errors via `console.error("ERROR order-history: ...")`.
- `pg.Pool` `connectionTimeoutMillis=2000`, `statement_timeout=2000`.
- Redis `connectTimeout=2000`.

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
