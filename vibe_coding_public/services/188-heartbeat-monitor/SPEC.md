# 188-heartbeat-monitor

Liveness aggregator. Each upstream service POSTs a heartbeat (`/beat`) with its current HTTP status code; the latest heartbeat per `service_id` is cached in `redis-cache` as `hb:{service_id}` with a 30 s TTL. Any non-200 status emits an `events:hb_down` event on the `redis-stream` so on-call dashboards can react.

**Stack:** Rust / Axum (rust:1.77-slim → debian:bookworm-slim)
**Deps:** redis-cache, redis-stream

## Endpoints
- `GET /healthz`
- `POST /beat` — body `{service_id, status_code}` → `SET hb:{service_id} status_code EX 30`; if `status_code != 200`, `XADD events:hb_down`
- `GET /status/:service_id` — returns `alive` (with last status_code) or `dead`
- `GET /alive` — `SCAN hb:*` → list of currently-alive `service_id`s
- `GET /alarms` — `XREVRANGE events:hb_down + - COUNT 50`

All Redis operations use a 2 s `tokio::time::timeout`. All errors logged via `tracing::error!("heartbeat-monitor: …")`.
