# 86-loan-originator

**Language**: Kotlin/Ktor  **Deps**: postgres, redis-cache

## Endpoints
- `GET  /healthz`
- `POST /loans/apply` body: `{user_id, amount_cents, purpose}` → DB insert + Redis HSET loan:{id}
- `GET  /loans/:id/status` → Redis HGETALL first, fallback to DB
- `PUT  /loans/:id/approve` → DB update + Redis HSET status=approved

## Table
`loans(id serial PK, user_id text, amount_cents bigint, purpose text, status text DEFAULT 'pending', applied_at timestamptz)`
