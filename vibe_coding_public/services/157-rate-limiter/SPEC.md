# 157-rate-limiter

Go/chi rate-limiting service using Redis fixed-window counters per key.

Endpoints: `GET /healthz`, `POST /configure` (set limit + window for key), `POST /check` (INCR counter, returns allowed/remaining), `GET /usage/{key}`, `DELETE /limit/{key}` (clears config + counters).

Deps: redis-cache (`rl_cfg:{key}` hash with limit+window, `rl:{key}:{bucket}` counters with EXPIRE = window_seconds).
