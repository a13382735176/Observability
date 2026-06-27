# 150-status-page

Public status / incident banner service. Records per-component states in a Redis cache (`status:{component}` hash with 600s TTL) and holds an optional `banner` key (JSON, 3600s TTL) for global incident announcements.

Stack: Java 21 / Spring Boot 3.3.0 / Spring Data Redis (Jedis).

Deps: redis-cache.

## Endpoints

- `GET /healthz`
- `POST /status` — body `{ component, state: "operational"|"degraded"|"down", message? }`; `HSET status:{component}` + `EXPIRE 600`
- `GET /status/:component` — `HGETALL status:{component}`
- `GET /status` — `SCAN match status:*` returning all components
- `POST /incident/banner` — body `{ message, severity }`; `SET banner <json> EX 3600`
- `GET /incident/banner` — `GET banner`

## Schema

Keys in `redis-cache`:

```
status:{component}  (HASH)  fields: state, message, ts          TTL=600s
banner              (STRING JSON: {message, severity, ts})      TTL=3600s
```

All Redis calls use 2s connect/read timeouts via `JedisConnectionFactory`. Failures log `ERROR status-page: ...` (via SLF4J `log.error("status-page: ...")`) and return HTTP 503.
