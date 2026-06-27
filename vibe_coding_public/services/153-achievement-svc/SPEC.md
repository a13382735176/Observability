# 153-achievement-svc

Python/Flask service that tracks achievement definitions and per-user unlocks.
Postgres is the source of truth; a per-user redis set caches the unlocked
achievement codes.

## Dependencies
- postgres (`achievement_defs`, `user_achievements`)
- redis-cache (per-user achievement sets at `ach:{user_id}`)

## Endpoints
- `GET /healthz`
- `POST /achievements` → body `{code, name, description?, points?}`. Upserts
  the achievement definition.
- `GET /achievements` → all definitions ordered by `code`.
- `POST /unlock` → body `{user_id, achievement_code}`. Idempotent INSERT into
  `user_achievements`, plus `SADD ach:{user_id} {code}`.
- `GET /achievements/{user_id}` → cache-first read; falls back to postgres on a
  miss and repopulates the redis set.

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
