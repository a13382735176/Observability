# feature-flag-svc

Per-flag rollout management. Go/chi + Redis-cache. Hash(user_id+flag) % 100 vs rollout_pct.

## Endpoints
- `POST /flags` body `{name,enabled,rollout_pct}` → HSET `flags:{name}`
- `GET /flags/:name` → 404 if missing
- `GET /flags/all` → KEYS `flags:*`
- `POST /check` body `{name,user_id}` → deterministic bucket assignment
