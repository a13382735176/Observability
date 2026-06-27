# 155-chat-room

Group chat room service. Persists rooms, messages, and memberships in Postgres; publishes every new message to a per-room Redis stream `events:chat:{room_id}` via `XADD` for downstream fan-out.

**Stack:** Kotlin / Ktor 2.3.12 (gradle:8.7-jdk21 → eclipse-temurin:21-jre-jammy)
**Deps:** postgres, redis-stream (Jedis pool, 2 s timeout, maxTotal=4)

Endpoints: `GET /healthz`, `POST /rooms`, `GET /rooms`, `POST /rooms/:id/messages`, `GET /rooms/:id/messages` (last 50), `POST /rooms/:id/join`. Errors logged as `chat-room: ...` at ERROR via SLF4J.
