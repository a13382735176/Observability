# article-service

Content article storage and retrieval service. Python/FastAPI + Postgres + Redis-cache.

## Endpoints
- `GET  /healthz` → `{"status":"ok","service":"article-service"}`
- `POST /articles` body `{"title":"...","content":"...","author_id":"..."}` → 201 + article JSON; stored in postgres + cached `art:{id}` 300s
- `GET  /articles` → list up to 50 articles from postgres (newest first)
- `GET  /articles/:id` → cache-first, fallback postgres

## Table
```sql
articles(id serial PRIMARY KEY, title text NOT NULL, content text NOT NULL, author_id text NOT NULL, published_at timestamptz DEFAULT NOW())
```

## Fault behaviour
- Postgres failure → HTTP 502, `ERROR article-service: ...` in logs
- Redis failure → cache miss, falls back to postgres (logged as ERROR)
