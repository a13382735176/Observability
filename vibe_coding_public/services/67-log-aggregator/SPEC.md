# 67-log-aggregator

IoT device logs (Kotlin/Ktor).

## Deps
- postgres
- redis-stream

## Endpoints
- GET /healthz
- POST /logs {device_id, level, message}
- GET /logs/:device_id

## Table
device_logs(id serial, device_id text, level text, message text, ts timestamptz)
