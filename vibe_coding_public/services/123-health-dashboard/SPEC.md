# health-dashboard

Aggregated per-service health status with 5-min TTL. C#/.NET8 + Redis-cache.

## Endpoints
- `POST /report` body `{service_name, status, latency_ms}` → HSET health:{service_name}; EXPIRE 300
- `GET  /health/:service_name`
- `GET  /health/summary` → map of all `health:*` keys to their fields
