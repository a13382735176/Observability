# 34-stock-notifier
Stock availability notifications: subscribes users per SKU in Postgres, publishes to stream.
**Deps**: postgres, redis-stream  **Lang**: Rust/Actix
**Endpoints**: GET /healthz, POST /subscribe, GET /subscriptions/:sku, POST /notify
**Faults**: F01 F02 F05 F06 F09 F10 F11 F12 F13
