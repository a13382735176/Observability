# circuit-breaker

Per-service success/fail counter with simple open/closed state. Kotlin/Ktor + Redis-cache.

## Endpoints
- `POST /record` body `{service_name, success}` → HINCRBY cb:{service_name} success|fail
- `GET  /state/:service_name` → `{state:"open"|"closed", success, fail, fail_rate}`. Open when total ≥ 10 and fail_rate > 0.5.
- `POST /reset/:service_name` → 204
