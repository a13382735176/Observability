# 184-device-registry

Go/chi service that registers IoT devices, with redis as a read-through cache for the
hot path of looking up a device by its `device_id`.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"device-registry"}`
- `POST /devices` → body `{device_id, model, firmware_version, owner_id}`; upsert (ON CONFLICT device_id); HSET + EXPIRE 600s.
- `GET /devices/{device_id}` → HGETALL Redis first; on miss SELECT postgres + cache.
- `PUT /devices/{device_id}/firmware` → body `{firmware_version}`; UPDATE + DEL cache.
- `GET /devices/owner/{owner_id}` → up to 100 devices for the owner.
- `DELETE /devices/{device_id}` → DELETE row + DEL cache.

## Schema
```
devices(id bigserial PK, device_id text unique, model text, firmware_version text,
        owner_id text,
        registered_at timestamptz default now(),
        updated_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
