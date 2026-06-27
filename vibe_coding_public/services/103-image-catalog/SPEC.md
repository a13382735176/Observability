# image-catalog

Content image storage metadata service. Go/gin + Postgres + Redis-cache.

## Endpoints
- `GET  /healthz` → `{"status":"ok","service":"image-catalog"}`
- `POST /images` body `{"filename":"...","width":N,"height":N,"url":"..."}` → 201; stored in postgres + cached `img:{id}` 5m
- `GET  /images/:id` → cache-first, fallback postgres
- `GET  /images?width_min=X` → filter by minimum width

## Table
```sql
images(id serial PRIMARY KEY, filename text NOT NULL, width int NOT NULL, height int NOT NULL, url text NOT NULL, created_at timestamptz DEFAULT NOW())
```

## Fault behaviour
- Postgres failure → HTTP 502, `ERROR image-catalog: ...` in logs
- Redis failure → cache miss, falls back to postgres (logged as ERROR)
