# 82-escrow-service

**Language**: Elixir/Plug+Cowboy  **Deps**: postgres, redis-cache

## Endpoints
- `GET  /healthz`
- `POST /escrows` body: `{payer_id, payee_id, amount_cents, condition}` → DB insert + Redis HSET
- `GET  /escrows/:id` → Redis HGETALL first, fallback to DB
- `POST /escrows/:id/release` → DB UPDATE status=released + Redis DEL

## Tables
`escrows(id serial PK, payer_id text, payee_id text, amount_cents bigint, condition text, status text DEFAULT 'held', created_at timestamptz)`
