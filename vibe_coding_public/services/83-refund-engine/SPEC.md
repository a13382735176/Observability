# 83-refund-engine

**Language**: TypeScript/Fastify  **Deps**: postgres, redis-stream

## Endpoints
- `GET  /healthz`
- `POST /refunds` body: `{payment_id, amount_cents, reason}` → DB + XADD events:refunds
- `GET  /refunds/:payment_id` → list refunds for payment
- `GET  /refund/:id/status` → status of single refund

## Table
`refunds(id serial PK, payment_id int, amount_cents bigint, reason text, status text DEFAULT 'pending', created_at timestamptz)`
