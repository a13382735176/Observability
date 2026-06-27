# 78-ledger-service

Financial double-entry ledger (Java/Spring Boot).

## Deps
- postgres

## Endpoints
- GET /healthz
- POST /entries {debit_account, credit_account, amount_cents, description}
- GET /entries/:account
- GET /balance-sheet

## Table
ledger_entries(id serial, debit_account text, credit_account text, amount_cents bigint, description text, ts timestamptz)
