# 84-statement-gen

**Language**: Go/fiber  **Deps**: postgres

## Endpoints
- `GET  /healthz`
- `POST /generate` body: `{account_id, from_date, to_date}` → saves statement with net_cents=0
- `GET  /statements/:account_id` → list statements for account
- `GET  /statement/:id` → single statement by id

## Table
`statements(id serial PK, account_id text, from_date date, to_date date, net_cents bigint DEFAULT 0, generated_at timestamptz)`
