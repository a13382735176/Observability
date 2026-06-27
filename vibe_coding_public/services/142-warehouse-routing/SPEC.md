# 142-warehouse-routing

Rust/Axum service that registers warehouses and computes a coarse warehouse-to-zip routing
decision. Postgres stores the warehouses table; redis-cache stores per-region listings (300s)
and resolved route decisions per origin/dest zip pair (600s).

## Stack
- Rust / Axum (`rust:1.77-slim` → `debian:bookworm-slim`)
- sqlx `PgPool` with `acquire_timeout = 2s`
- `redis::Client` (TLS off)

## Deps
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"warehouse-routing"}`
- `POST /warehouses` — body `{name, region, capacity:i32}` → `INSERT INTO warehouses … RETURNING *`
- `GET /warehouses/:region` — `SELECT * … WHERE region=$1`; cache key `wh:{region}` 300s
- `POST /route` — body `{origin_zip, dest_zip}` → match warehouses whose region starts with the
  first 2 chars of `dest_zip`, return `{warehouse_id, distance:0}`; cache key `route:{origin}:{dest}` 600s
- `GET /warehouses` — list all

## Schema
```
warehouses(id bigserial PK,
           name text,
           region text,
           capacity int,
           created_at timestamptz default now())
```

## Logging / timeouts
- All errors via `tracing::error!("warehouse-routing: {}", e)`.
- Per-operation 2s timeouts on every postgres and redis call.

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
