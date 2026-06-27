# 160-metric-ingest

Java/Spring Boot 3.3.0 (Java 21) metric ingestion service. Accepts metric samples,
persists them in Postgres, and caches the latest value per metric in Redis (TTL 300s).

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"metric-ingest"}`
- `POST /metrics` → body `{name, value, tags, ts_epoch_ms?}`; persists; updates `metric:latest:{name}` in Redis.
- `POST /metrics/batch` → JSON array of metric samples; batch insert + Redis update per entry.
- `GET /metrics/{name}` → Redis-cache first; on miss return latest sample from DB.
- `GET /metrics/{name}/series?from=&to=` → time-range query (LIMIT 500).

## Schema
```
metric_samples(id bigserial PK, name text, value double precision,
               tags jsonb default '{}', ts timestamptz default now())
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
