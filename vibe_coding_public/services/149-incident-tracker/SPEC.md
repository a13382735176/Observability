# 149-incident-tracker

Incident / outage tracker. Persists incidents in Postgres with severity and affected service, emits creation and resolution events to Redis Streams (`events:incidents`, `events:incident_resolved`), and exposes filters for active and per-service incidents.

Stack: Go / gin / pgx / go-redis.

Deps: postgres, redis-stream.

## Endpoints

- `GET /healthz`
- `POST /incidents` — body `{ title, severity: 1..5, description, affected_service }`; inserts row + `XADD events:incidents {id, severity}`
- `GET /incidents/:id`
- `GET /incidents/active` — `WHERE resolved_at IS NULL`
- `PUT /incidents/:id/resolve` — body `{ resolution }`; sets `resolved_at=now()` + `XADD events:incident_resolved`
- `GET /incidents/by-service/:service_name`

## Schema

```sql
CREATE TABLE IF NOT EXISTS incidents(
  id BIGSERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  severity INT NOT NULL,
  description TEXT,
  affected_service TEXT,
  resolution TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
```

All DB and Redis calls use 2s timeouts. Failures log `ERROR incident-tracker: ...` and return HTTP 503.
