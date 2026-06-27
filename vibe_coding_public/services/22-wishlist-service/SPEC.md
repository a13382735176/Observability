# 22-wishlist-service
User wishlist management storing items in Redis SETs.
**Deps**: redis-cache  **Lang**: Rust/Axum
**Endpoints**: GET /healthz, GET /wishlist/:user_id, POST /wishlist/:user_id/items, DELETE /wishlist/:user_id
**Faults**: F01 F02 F07 F08 F11 F12 F13
