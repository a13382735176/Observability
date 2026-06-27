# 183-iot-telemetry

Python/FastAPI service that ingests sensor readings from IoT devices, persists them in postgres,
and publishes anomaly events to a redis stream when a reading is outside `[0, 100]`.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"iot-telemetry"}`
- `POST /readings` → body `{device_id, sensor_type, value, ts_epoch_ms?}`; inserts; XADDs to `events:sensors` when `value > 100` or `value < 0`.
- `GET /readings/{device_id}` → last 100 readings.
- `GET /readings/{device_id}/avg?since_minutes=60` → average value per sensor_type over the window.
- `POST /readings/batch` → body `{readings:[...]}`; bulk insert + per-row anomaly event.
- `GET /devices` → up to 100 distinct device IDs.

## Schema
```
sensor_readings(id bigserial PK, device_id text, sensor_type text,
                value double precision, ts timestamptz default now())
INDEX (device_id, ts DESC)
INDEX (sensor_type, ts DESC)
```

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
