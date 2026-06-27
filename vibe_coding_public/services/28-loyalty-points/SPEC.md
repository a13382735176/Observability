# 28-loyalty-points
Loyalty point tracking with Postgres persistence and Redis balance cache.
**Deps**: postgres, redis-cache  **Lang**: Rust/Axum
**Endpoints**: GET /healthz, GET /points/:user_id, POST /earn, POST /redeem
**Faults**: F01 F02 F05 F06 F07 F08 F11 F12 F13
