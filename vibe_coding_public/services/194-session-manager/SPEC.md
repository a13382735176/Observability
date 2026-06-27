# 194-session-manager

User session manager. Stores session records in `redis-cache` (`sess:{session_id}` JSON blob EX 86400) with a per-user reverse index (`user_sess:{user_id}` SET of session_ids), and emits login/logout events to `redis-stream` (`events:logins`, `events:logouts`).

**Stack:** Go / chi (golang:1.22-alpine → alpine:3.20)
**Deps:** redis-cache, redis-stream

## Endpoints
- `GET /healthz`
- `POST /sessions` — body `{user_id, ip_address, user_agent}` → generate hex(24) session_id, SET cache, SADD user index, XADD `events:logins` → `{session_id, expires_in:86400}`
- `GET /sessions/{session_id}` — cache GET → `{valid, user_id?, ip?, ua?, created_at?}`
- `DELETE /sessions/{session_id}` — read user_id from cache, DEL key, SREM user index, XADD `events:logouts`
- `GET /sessions/user/{user_id}` — SMEMBERS user index, GET each session → list
- `POST /sessions/{session_id}/refresh` — EXPIRE 86400 on the cache key

Two redis clients: `REDIS_CACHE_HOST` for SET/GET/SMEMBERS/EXPIRE, `REDIS_STREAM_HOST` for XADD. `go-redis` `Options{DialTimeout:2s, ReadTimeout:2s, WriteTimeout:2s}` + per-request 2s `context.WithTimeout`. All errors logged via `log.Printf("ERROR session-manager: %v", err)`.
