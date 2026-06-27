# 147-knowledge-base-svc

Knowledge base / wiki article service. Stores articles with full-text searchable title and body plus a `text[]` tag array in Postgres. Exposes search by substring and filter by tag.

Stack: TypeScript / Express / pg.

Deps: postgres.

## Endpoints

- `GET /healthz`
- `POST /articles` — body `{ title, body, tags: [string] }`
- `GET /articles/:id`
- `GET /articles?tag=X` — list articles where `X` is in `tags`
- `GET /articles/search?q=Y` — case-insensitive substring match on title or body, limit 20
- `PUT /articles/:id` — partial update (title, body, tags any subset)

## Schema

```sql
CREATE TABLE IF NOT EXISTS kb_articles(
  id bigserial PRIMARY KEY,
  title text NOT NULL,
  body text NOT NULL,
  tags text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz
);
```

All DB calls use 2s connection/statement/query timeouts. Failures log `ERROR knowledge-base-svc: ...` and return HTTP 503.
