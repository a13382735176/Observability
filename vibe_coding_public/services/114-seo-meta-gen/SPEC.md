# 114-seo-meta-gen

Python/FastAPI service for seo-meta-gen. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: postgres, redis-cache. Faults: F01, F02, F05, F06, F07, F08, F11, F12, F13.
