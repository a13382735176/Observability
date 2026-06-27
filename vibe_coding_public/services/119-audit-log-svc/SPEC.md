# audit-log-svc

Compliance audit trail. Python/FastAPI + Postgres (source of truth) + Redis-stream (events:audit).

## Endpoints
- `POST /events` body `{actor_id, action, resource_type, resource_id, details}` → postgres + XADD
- `GET  /events/:actor_id` → last 50 by actor
- `GET  /events/resource/:resource_id` → last 50 by resource

## Table
```sql
CREATE TABLE audit_events (
  id SERIAL PRIMARY KEY,
  actor_id TEXT, action TEXT, resource_type TEXT, resource_id TEXT,
  details JSONB DEFAULT '{}', ts TIMESTAMPTZ DEFAULT NOW()
);
```
