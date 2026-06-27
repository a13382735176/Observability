# 190-signal-relay

Kotlin/Ktor WebRTC signaling relay. Stores signaling messages (offers/answers/ICE candidates) and active call sessions in Postgres; publishes per-recipient signal events to Redis Streams.

Endpoints: GET /healthz, POST /signals, GET /signals/:user_id, POST /sessions, POST /sessions/:session_id/end, GET /sessions/active.

Deps: postgres (signals, sessions tables — auto-created), redis-stream (events:signal:{user_id} streams).
