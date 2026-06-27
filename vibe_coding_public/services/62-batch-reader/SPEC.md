# 62-batch-reader

IoT batch reader (TypeScript/Express, redis-stream).

## Deps
- redis-stream

## Endpoints
- GET /healthz
- GET /stats
- POST /read — {count} msgs from events:telemetry
