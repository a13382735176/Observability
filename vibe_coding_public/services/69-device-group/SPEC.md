# 69-device-group

IoT device grouping (Kotlin/Ktor).

## Deps
- postgres

## Endpoints
- GET /healthz
- POST /groups {name, device_ids}
- GET /groups
- GET /groups/:id/devices
- POST /groups/:id/add {device_id}

## Tables
groups(id serial, name text unique)
group_devices(group_id int, device_id text)
