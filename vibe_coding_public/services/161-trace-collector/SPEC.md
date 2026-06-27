# 161-trace-collector

Python/FastAPI distributed-trace collector. Accepts spans, persists them in Postgres, and
publishes slow traces (duration > 1s) to a Redis Stream (`events:traces`).

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"trace-collector"}`
- `POST /spans` → body `{trace_id, span_id, parent_span_id?, service, operation, start_ns, duration_ns, attributes}`; persists; if `duration_ns > 1_000_000_000`, XADD to `events:traces`.
- `GET /traces/{trace_id}` → all spans for trace, ordered by `start_ns ASC`.
- `GET /traces/recent` → up to 50 distinct trace IDs from the last 1000 spans.
- `GET /slow` → up to 20 most-recent slow-trace events from `events:traces`.

## Schema
```
spans(id bigserial PK, trace_id text, span_id text, parent_span_id text,
      service text, operation text, start_ns bigint, duration_ns bigint,
      attributes jsonb default '{}', recorded_at timestamptz default now())
```
Indexes: `(trace_id)`, `(service, recorded_at DESC)`.

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
