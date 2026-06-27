# 17-pricing-engine
Dynamic pricing API storing all SKU prices in a Redis HASH.
**Deps**: redis-cache  **Lang**: Go/gin
**Endpoints**: GET /healthz, GET /price/:sku, PUT /price/:sku, GET /prices
**Faults**: F01 F02 F07 F08 F11 F12 F13
