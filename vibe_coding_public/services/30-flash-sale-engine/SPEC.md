# 30-flash-sale-engine
Time-limited flash sales with Redis TTL for active sales and stream for purchases.
**Deps**: redis-cache, redis-stream  **Lang**: Python/FastAPI
**Endpoints**: GET /healthz, GET /sales/active, POST /sales, POST /purchase
**Faults**: F01 F02 F07 F08 F09 F10 F11 F12 F13
