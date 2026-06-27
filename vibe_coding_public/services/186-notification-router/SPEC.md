# 186-notification-router

Multi-channel notification fanout for a single user. Channels (`email`, `sms`, `push`, ...) are registered per user_id in Postgres `user_channels` and mirrored into a Redis set `ch:{user_id}` for fast lookups. `POST /route` looks the user's channels up in Redis first, falls back to Postgres on cache miss, then inserts one row into `routed_notifications` per matched channel and returns the list it routed to.

Endpoints: `GET /healthz`, `POST /channels`, `GET /channels/{user_id}`, `DELETE /channels/{id}`, `POST /route`, `GET /notifications/{user_id}`.
