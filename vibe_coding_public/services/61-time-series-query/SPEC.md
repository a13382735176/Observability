# 61-time-series-query

IoT time-series query service (Elixir/Plug+Cowboy).

## Deps
- postgres (PG_DSN)

## Endpoints
- GET /healthz
- POST /datapoints — insert {device_id, metric, value, ts_iso}
- GET /series/:device_id?metric=temp — last 100 rows

## Table
datapoints(id serial, device_id text, metric text, value real, ts timestamptz)
