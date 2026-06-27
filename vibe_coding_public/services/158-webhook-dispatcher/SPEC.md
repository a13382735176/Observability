# 158-webhook-dispatcher

Python/FastAPI service that persists webhook subscriptions and dispatches events to subscriber HTTP endpoints, recording delivery outcomes.

Endpoints: `GET /healthz`, `POST /subscriptions`, `GET /subscriptions` (filterable by `event_type`), `DELETE /subscriptions/{id}`, `POST /dispatch` (looks up subscribers by event_type, POSTs payload with 2s timeout), `GET /deliveries` (last 50).

Deps: postgres (tables `webhook_subscriptions`, `webhook_deliveries`), upstream HTTP target (`UPSTREAM_URL` env, default `http://mock-upstream:8080`).
