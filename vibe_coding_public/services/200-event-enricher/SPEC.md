# 200-event-enricher

TypeScript/Express service that enriches incoming events with persistence and stream fan-out.
It stores canonical events in Postgres and publishes compact notifications to redis-stream.

Endpoints: `GET /healthz`, `POST /enrich`, `GET /enrich/{id}`, `GET /recent?limit=`.

Dependencies: postgres, redis-stream. Faults: F01, F02, F05, F06, F09, F10, F11, F12, F13.
