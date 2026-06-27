# 174-cohort-builder

User cohort definition + evaluation service. Stores cohort criteria (event_type / min_count / since_days) as JSONB, and computes membership against a synthetic `usage_events_fake` table (pre-populated with ~50 rows on startup) by counting per-user events within the lookback window.

**Stack:** TypeScript / Fastify on `node:20-alpine`
**Deps:** postgres (2 s `connectionTimeoutMillis` + `statement_timeout`)

## Endpoints
- `GET /healthz`
- `POST /cohorts` — body `{name, criteria:{event_type, min_count, since_days}}`
- `POST /cohorts/:id/evaluate` — runs criteria → inserts matching users into `cohort_members`, returns `{cohort_id, member_count}`
- `GET /cohorts/:id` — cohort + member_count
- `GET /cohorts/:id/members?limit=100`
- `GET /cohorts` — list

Errors logged as `cohort-builder: ...` at ERROR level.

## Schema
```sql
CREATE TABLE cohorts(id bigserial PRIMARY KEY, name text, criteria jsonb, created_at timestamptz DEFAULT now());
CREATE TABLE cohort_members(id bigserial PRIMARY KEY, cohort_id bigint, user_id text, added_at timestamptz DEFAULT now());
CREATE TABLE usage_events_fake(id bigserial PRIMARY KEY, user_id text, event_type text, ts timestamptz DEFAULT now());
```
