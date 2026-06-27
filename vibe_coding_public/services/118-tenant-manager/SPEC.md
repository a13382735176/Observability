# tenant-manager

Multi-tenant CRUD. Java/Spring Boot 3.3 + Postgres + Redis-cache (read-through).

## Endpoints
- `POST /tenants` body `{name,plan,domain}` → postgres insert + redis HSET
- `GET  /tenants/:id` → cache first, postgres fallback
- `PUT  /tenants/:id/plan` body `{plan}` → postgres update + cache invalidate
- `GET  /tenants` → list from postgres

## Table
```sql
CREATE TABLE tenants (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  plan TEXT NOT NULL,
  domain TEXT UNIQUE NOT NULL,
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```
