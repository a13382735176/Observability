# 148-feedback-collector

User feedback / NPS collector. Stores each submission in Postgres and emits a
`{id, rating}` event to a Redis Stream (`events:feedback`) for downstream
processors. Exposes aggregate stats by source.

Stack: Python / FastAPI / psycopg / redis-py.

Deps: postgres, redis-stream.

## Endpoints

- `GET /healthz`
- `POST /feedback` — body `{ source, message, rating: 1..5, user_id? }`; inserts row + `XADD events:feedback`
- `GET /feedback/{id}`
- `GET /feedback/by-source/{source}` — last 50 rows for that source
- `GET /feedback/stats` — `avg(rating)` and count grouped by source

## Schema

```sql
CREATE TABLE IF NOT EXISTS user_feedback(
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  message TEXT NOT NULL,
  rating INT NOT NULL,
  user_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

All DB and Redis calls use 2s timeouts. Failures log `ERROR feedback-collector: ...` and return HTTP 503.
