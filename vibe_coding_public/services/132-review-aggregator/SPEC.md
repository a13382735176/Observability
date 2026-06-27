# 132-review-aggregator

Rust/Axum service that accepts product/entity reviews, persists them in postgres,
and returns cached aggregate stats (average rating, count) using redis as a 5-minute cache.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"review-aggregator"}`
- `POST /reviews` → body `{entity_id, entity_type, rating, body, author_id}`; persists row.
- `GET /reviews/{entity_id}` → last 50 reviews for the entity.
- `GET /aggregate/{entity_type}/{entity_id}` → `{avg, count}` (cache TTL 300s).

## Schema
```
aggregated_reviews(id serial PK, entity_id text, entity_type text,
                   rating int, body text, author_id text,
                   created_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
