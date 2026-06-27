# quota-enforcer

Per-API-key per-hour quota counter. Go/chi + Redis-cache (counts) + Redis-stream (over-quota events).

## Endpoints
- `POST /quotas/:api_key` body `{limit_per_hour}` → HSET qlimit:{api_key}
- `GET  /quotas/:api_key`
- `POST /check` body `{api_key, resource}` → INCR quota:{api_key}:{resource}:{YYYYMMDDHH}; EXPIRE 3600 first time. Returns `{allowed, count, limit, remaining}`. On over-quota: XADD events:quota_exceeded.
