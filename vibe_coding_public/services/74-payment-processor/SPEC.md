# 74-payment-processor

Financial payments (Rust/Axum).

## Deps
- postgres
- redis-stream

## Endpoints
- GET /healthz
- POST /payments
- GET /payments/:id
- GET /payments/user/:user_id

## Table
payments(id serial, payer_id text, payee_id text, amount_cents bigint, currency text, status text, ts timestamptz)
