# 64-provisioning-svc

IoT device provisioning (Go/chi).

## Deps
- postgres
- redis-cache

## Endpoints
- GET /healthz
- POST /provision {device_id, device_type}
- GET /provision/:device_id

## Table
provisions(id serial, device_id text unique, device_type text, api_token text, provisioned_at timestamptz)
