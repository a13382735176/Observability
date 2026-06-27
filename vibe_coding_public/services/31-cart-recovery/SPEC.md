# 31-cart-recovery
Abandoned cart recovery storing carts in Redis and publishing events to stream.
**Deps**: redis-cache, redis-stream  **Lang**: Go/fiber
**Endpoints**: GET /healthz, GET /abandoned-carts, POST /abandon, DELETE /carts/:user_id
**Faults**: F01 F02 F07 F08 F09 F10 F11 F12 F13
