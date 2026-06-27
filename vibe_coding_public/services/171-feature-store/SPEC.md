# 171-feature-store

Rust/Axum service that stores per-entity feature values (an ML feature store) in postgres,
caching the most-recent value per `(entity_id, feature_name)` in redis with a 10-minute TTL.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"feature-store"}`
- `POST /features` → body `{entity_id, feature_name, value:float, version:int}`; INSERT row, SET `feat:{entity_id}:{feature_name}` value EX 600.
- `GET /features/{entity_id}/{feature_name}` → cache lookup first, on miss SELECT latest version and SET cache.
- `GET /features/entity/{entity_id}` → latest version per `feature_name` for the entity.
- `POST /features/batch` → array of `{entity_id, feature_name, value, version}`; batch INSERT.

## Schema
```
features(id bigserial PK, entity_id text, feature_name text,
         value double precision, version int default 1,
         created_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
