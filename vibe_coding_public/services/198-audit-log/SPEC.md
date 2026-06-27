# 198-audit-log

Go/chi service that records audit events in Postgres (`audit_log` table with indexes on actor/resource/success) and publishes to two Redis streams: `events:audit` for every event and `events:audit_failures` for events with `success=false`.

Endpoints: `GET /healthz`, `POST /audit`, `GET /audit/{id}`, `GET /audit/actor/{actor}?limit=`, `GET /audit/resource/{resource}?limit=`, `GET /audit/recent` (last 100), `GET /audit/failures` (last 50 from stream).

Dependencies: postgres, redis-stream. Faults: F01, F02, F05, F06, F09, F10, F11, F12, F13.
