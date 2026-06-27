# 70-obd-parser

IoT OBD-II parser (Rust/Axum).

## Deps
- redis-cache
- redis-stream

## Endpoints
- GET /healthz
- POST /parse {pid, raw_value}
- GET /cached/:pid
