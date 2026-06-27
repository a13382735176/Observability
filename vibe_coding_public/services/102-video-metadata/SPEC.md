# video-metadata

Content video metadata service. TypeScript/Express + Postgres.

## Endpoints
- `GET  /healthz` → `{"status":"ok","service":"video-metadata"}`
- `POST /videos` body `{"title":"...","duration_s":N,"url":"...","tags":["..."]}` → 201 + video JSON
- `GET  /videos/:id` → single video
- `GET  /videos?tag=X` → filter by tag (JSONB contains)

## Table
```sql
videos(id serial PRIMARY KEY, title text NOT NULL, duration_s int NOT NULL, url text NOT NULL, tags jsonb DEFAULT '[]', created_at timestamptz DEFAULT NOW())
```

## Fault behaviour
- Postgres failure → HTTP 502, `ERROR video-metadata: ...` in logs
