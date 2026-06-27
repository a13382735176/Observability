# 79-credit-score

Financial credit score (Go/echo, postgres+redis-cache).

## Deps
- postgres
- redis-cache

## Endpoints
- GET /healthz
- GET /score/:user_id
- POST /compute {user_id, payment_history_pct, credit_utilization_pct}

## Table
credit_scores(id serial, user_id text unique, score int, computed_at timestamptz)
