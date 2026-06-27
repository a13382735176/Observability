# 19-recommendation-api
Product recommendation service reading from event stream, caching in Redis.
**Deps**: redis-cache, redis-stream  **Lang**: TypeScript/Fastify
**Endpoints**: GET /healthz, GET /recommendations/:user_id, POST /events
**Faults**: F01 F02 F07 F08 F09 F10 F11 F12 F13
