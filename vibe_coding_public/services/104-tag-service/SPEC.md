# 104-tag-service

Python/FastAPI service for tag-service. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: redis-cache. Faults: F01, F02, F07, F08, F11, F12, F13.
