# 77-recurring-billing

Financial recurring billing (Kotlin/Ktor).

## Deps
- postgres
- redis-stream

## Endpoints
- GET /healthz
- POST /schedules {user_id, amount_cents, interval_days}
- GET /schedules/:user_id
- POST /trigger/:schedule_id

## Table
billing_schedules(id serial, user_id text, amount_cents int, interval_days int, next_run timestamptz, active bool)
