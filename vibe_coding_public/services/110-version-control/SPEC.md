# 110-version-control

Python/FastAPI service for version-control. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: postgres, redis-stream. Faults: F01, F02, F05, F06, F09, F10, F11, F12, F13.
