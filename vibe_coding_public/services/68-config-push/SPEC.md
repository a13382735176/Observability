# 68-config-push

IoT config push (C#/.NET8).

## Deps
- postgres
- redis-cache

## Endpoints
- GET /healthz
- POST /configs {device_id, config}
- GET /configs/:device_id
- GET /pending

## Table
device_configs(id serial, device_id text unique, config text, pushed_at timestamptz, version int default 1)
