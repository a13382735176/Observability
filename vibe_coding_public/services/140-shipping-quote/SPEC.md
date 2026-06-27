# 140-shipping-quote

Shipping rate quoter with read-through cache against `mock-upstream`. Quotes are keyed by `(origin_zip, dest_zip, weight_kg)` and cached in `redis-cache` for 5 minutes.

**Stack:** TypeScript / Express (node:20-alpine)
**Deps:** redis-cache, upstream (mock-upstream)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"shipping-quote"}`
- `POST /quote` — body `{origin_zip, dest_zip, weight_kg}` — `cacheKey = "ship:<origin>:<dest>:<weight>"`. Tries `GET cacheKey`; on miss `POST <UPSTREAM_URL>/shipping` (2 s `AbortController` timeout) expecting `{rate_cents:int}`, then `SETEX cacheKey 300 JSON.stringify(result)`. Returns `{source, data}`.
- `POST /quote/refresh` — `SCAN MATCH ship:*` and `DEL` every key found.
- `GET /quote/cached` — `SCAN MATCH ship:*` and return `[{key, value}]`.

No Postgres. All upstream / Redis errors logged as `console.error('ERROR shipping-quote: ...')`. 2 s upstream timeout via `AbortController`; Redis `connectTimeout: 2000`.
