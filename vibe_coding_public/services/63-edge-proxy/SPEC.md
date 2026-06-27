# 63-edge-proxy

IoT edge config cache (Elixir/Plug+Cowboy, redis-cache).

## Deps
- redis-cache

## Endpoints
- GET /healthz
- GET /config/:device_id
- PUT /config/:device_id
