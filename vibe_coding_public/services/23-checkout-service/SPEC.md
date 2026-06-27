# 23-checkout-service
Checkout flow: persists orders to Postgres and publishes events to Redis stream.
**Deps**: postgres, redis-stream  **Lang**: TypeScript/Express
**Endpoints**: GET /healthz, POST /checkout, GET /orders/:user_id
**Faults**: F01 F02 F05 F06 F09 F10 F11 F12 F13
