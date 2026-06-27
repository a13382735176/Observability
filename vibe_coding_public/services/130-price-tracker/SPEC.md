# 130-price-tracker

Route price tracker. Stores the latest price per route in `redis-cache` (`price:{route}` hash with curr/prev/ts), and emits a `events:price_changes` stream event on the `redis-stream` when the absolute price delta exceeds 100 cents.

**Stack:** Go / chi (golang:1.22-alpine → alpine:3.20)
**Deps:** redis-cache, redis-stream

## Endpoints
- `GET /healthz`
- `POST /track` — body `{route, current_price_cents}` → HGET prev, HSET hash, optional XADD on big change
- `GET /prices/:route` — HGETALL `price:{route}` (404 if absent)
- `GET /changes` — XREVRANGE `events:price_changes` + - COUNT 20

All errors logged via `log.Printf("ERROR price-tracker: …", err)`. 2 second timeouts on every Redis op (DialTimeout / ReadTimeout / WriteTimeout + per-request context).
