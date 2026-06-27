# 199-secret-rotation

Python/FastAPI service that rotates and tracks per-service secret versions.
It persists version metadata in Postgres and caches the latest version in redis-cache.

Endpoints: `GET /healthz`, `POST /rotate`, `GET /latest/{service_name}`, `GET /history/{service_name}?limit=`.

Dependencies: postgres, redis-cache. Faults: F01, F02, F05, F06, F07, F08, F11, F12, F13.
