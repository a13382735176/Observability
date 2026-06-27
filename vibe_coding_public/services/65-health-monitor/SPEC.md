# 65-health-monitor

IoT device health (Python/FastAPI).

## Deps
- postgres
- redis-cache

## Endpoints
- GET /healthz
- POST /heartbeat {device_id, cpu_pct, mem_pct}
- GET /unhealthy

## Table
heartbeats(id serial, device_id text, cpu_pct real, mem_pct real, ts timestamptz)
