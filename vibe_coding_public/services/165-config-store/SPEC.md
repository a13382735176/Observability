# 165-config-store

Environment-scoped key/value configuration store with cache-aside reads. Persists
config entries in Postgres (`config_entries`, unique on `(environment, key)`) and
caches resolved values in Redis with a 10 min TTL.

**Stack:** Kotlin / Ktor 2.3.12 (gradle:8.7-jdk21 → eclipse-temurin:21-jre-jammy)
**Deps:** postgres, redis-cache

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"config-store"}`
- `POST /config` — body `{key, value, environment}` → Postgres UPSERT + `SETEX cfg:{env}:{key} 600`
- `GET /config/:environment/:key` — Redis GET first; on miss reads Postgres and re-caches
- `GET /config/:environment` — lists all keys for the environment
- `DELETE /config/:environment/:key` — Postgres DELETE + Redis DEL
- `POST /config/:environment/snapshot` — returns all keys for the env as a map

## Schema (auto-created at startup)
```sql
CREATE TABLE IF NOT EXISTS config_entries(
  id bigserial PRIMARY KEY,
  environment text NOT NULL,
  key text NOT NULL,
  value text,
  updated_at timestamptz DEFAULT now(),
  UNIQUE(environment, key)
);
```

## Timeouts / logging
- JDBC `loginTimeout=2`, `connectTimeout=2`, `socketTimeout=2`.
- Jedis pool timeout 2000 ms (`maxTotal=4`).
- All errors logged via SLF4J as `log.error("config-store: {}", e.message, e)`.

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
