# 135-loyalty-mileage

C#/.NET 8 service for travel loyalty mileage tracking. Stores earn/redeem history in Postgres and caches per-user mile balance in Redis.

Endpoints: GET /healthz, POST /miles/earn, POST /miles/redeem, GET /miles/:user_id, GET /history/:user_id.

Deps: postgres (mileage_history table, auto-created), redis-cache (per-user balance counter).
