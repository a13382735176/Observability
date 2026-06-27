# 156-presence-tracker

C#/.NET 8 service tracking user online/offline presence via Redis with 60-second TTL heartbeats.

Endpoints: `GET /healthz`, `POST /heartbeat`, `GET /presence/{user_id}`, `GET /online`, `DELETE /heartbeat/{user_id}`.

Deps: redis-cache (`presence:{user_id}` strings with EX 60, `online_users` set; stale entries pruned on `/online`).
