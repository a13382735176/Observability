# 159-log-aggregator

Rust/Axum log aggregation service. Accepts structured log entries, persists them in Postgres,
and pushes error-level entries onto a Redis Stream (`events:errors`) for downstream consumers.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"log-aggregator"}`
- `POST /logs` → body `{service, level, message, fields}`; persists; if `level=="error"`, XADD to `events:errors`.
- `GET /logs?service=X&level=Y&limit=N` → filtered (default limit 50, max 200).
- `GET /logs/recent` → last 100 entries.
- `GET /errors/stream` → up to 50 most recent entries from `events:errors`.

## Schema
```
log_entries(id bigserial PK, service text, level text, message text,
            fields jsonb default '{}', created_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
