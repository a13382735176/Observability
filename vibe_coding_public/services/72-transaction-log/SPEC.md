# 72-transaction-log

Financial transaction log (Scala/http4s+doobie).

## Deps
- postgres
- redis-stream

## Endpoints
- GET /healthz
- POST /transactions
- GET /transactions/:account_id

## Table
transactions(id serial, account_id int, amount_cents bigint, tx_type text, description text, ts timestamptz)
