# 107-embed-service

Python/FastAPI service for embed-service. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: postgres. Faults: F01, F02, F05, F06, F11, F12, F13.
