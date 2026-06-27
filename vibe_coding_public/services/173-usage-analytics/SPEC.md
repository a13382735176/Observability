# 173-usage-analytics

Go/chi service that records product-usage events and maintains per-user, per-event-type
counters in redis (24h TTL), with aggregate queries served from postgres.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"usage-analytics"}`
- `POST /events` → body `{user_id, event_type, properties:object?}`; INSERT row; `INCR ucount:{user_id}:{event_type}`; `EXPIRE 86400`.
- `GET /events/user/{user_id}` → last 100 events for that user.
- `GET /counts/{user_id}` → SCAN `ucount:{user_id}:*` and return `{event_type: count}` map.
- `GET /events/type/{event_type}/recent` → last 100 events of that type.
- `GET /stats` → `SELECT event_type, count(*) GROUP BY event_type` (top 50).

## Schema
```
usage_events(id bigserial PK, user_id text, event_type text,
             properties jsonb DEFAULT '{}'::jsonb,
             ts timestamptz DEFAULT now())

CREATE INDEX usage_events_user_ts_idx       ON usage_events(user_id, ts DESC);
CREATE INDEX usage_events_event_type_ts_idx ON usage_events(event_type, ts DESC);
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
