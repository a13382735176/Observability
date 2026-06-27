# 111-translation-svc

Python/FastAPI service for translation-svc. It exposes health and dependency probing endpoints.

Endpoints: `GET /healthz`, `POST /probe`.

Dependencies: upstream. Faults: F01, F02, F03, F04, F11, F12, F13.
