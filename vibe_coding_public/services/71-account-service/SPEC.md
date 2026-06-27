# 71-account-service

Financial accounts (Java/Spring Boot).

## Deps
- postgres
- redis-cache

## Endpoints
- GET /healthz
- POST /accounts {user_id, account_type, currency}
- GET /accounts/:user_id
- GET /accounts/:id/balance

## Table
accounts(id serial, user_id text, account_type text, currency text, balance_cents bigint default 0, created_at timestamptz)
