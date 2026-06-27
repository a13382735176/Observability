# 112-draft-storage

Python/FastAPI service for draft-storage. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: postgres. Faults: F01, F02, F05, F06, F11, F12, F13.
