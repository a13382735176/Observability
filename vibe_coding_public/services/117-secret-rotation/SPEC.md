# secret-rotation

Secret versioning + audit. TS/Fastify + Postgres (audit log) + Redis-cache (value+TTL).

## Endpoints
- `POST /secrets` body `{name,value}` → postgres audit row v1, redis HSET TTL 86400
- `GET  /secrets/:name/metadata` → latest version + rotated_at (no value)
- `POST /secrets/:name/rotate` body `{new_value}` → audit row +1, redis update
