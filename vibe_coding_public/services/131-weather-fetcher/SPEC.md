# 131-weather-fetcher

Per-city weather lookup with cache-aside. Reads `wx:{city}` from `redis-cache` first; on miss fetches `mock-upstream:8080/weather?city={city}` and writes back with 5 min TTL.

**Stack:** Python / FastAPI (python:3.12-slim)
**Deps:** redis-cache, upstream (mock-upstream)

## Endpoints
- `GET /healthz`
- `GET /weather/{city}` — cache-aside → upstream → SETEX `wx:{city}` 300; 502 if upstream fails
- `GET /cached` — `{"cities": [strip wx: prefix from KEYS wx:*]}`

All errors logged via `log.error("weather-fetcher: %s", e)`. 2 s `socket_connect_timeout` / `socket_timeout` on Redis and 2.0 s on `httpx.AsyncClient`.
