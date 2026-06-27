# 89-transfer-service

**Language**: C#/.NET8  **Deps**: postgres, redis-stream

## Endpoints
- `GET  /healthz`
- `POST /transfers` body: `{from_account, to_account, amount_cents, reference}` → DB + XADD events:transfers
- `GET  /transfers/:id` → transfer by id
- `GET  /transfers/account/:account_id` → transfers for account

## Table
`transfers(id serial PK, from_account text, to_account text, amount_cents bigint, reference text, status text DEFAULT 'completed', ts timestamptz)`
