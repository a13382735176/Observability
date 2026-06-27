# 66-event-router

IoT event routing (Go/chi, redis-stream).

## Deps
- redis-stream

## Endpoints
- GET /healthz
- POST /route {event_type, payload}
- GET /stats
