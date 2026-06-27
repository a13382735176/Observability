# 170-cron-svc

TypeScript / Express service that registers cron-like schedules and tracks their runs.

## Dependencies
- postgres (tables `cron_jobs`, `cron_runs`)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"cron-svc"}`
- `POST /cron` body `{name, expression, action_url}` → 201;
  `next_run_at = now() + interval '60 seconds'`
- `GET /cron/:id` → row or 404
- `GET /cron/due` → up to 50 enabled jobs with `next_run_at <= now()`
- `PUT /cron/:id/enable` → set `enabled = true`
- `PUT /cron/:id/disable` → set `enabled = false`
- `POST /cron/:id/log` body `{status, error?}` → insert into `cron_runs`,
  then bump parent `next_run_at = now() + interval '60 seconds'`
- `GET /cron/:id/runs` → last 20 by id DESC

## Schema
```sql
CREATE TABLE IF NOT EXISTS cron_jobs (
    id bigserial PRIMARY KEY,
    name text,
    expression text,
    action_url text,
    enabled boolean DEFAULT true,
    next_run_at timestamptz DEFAULT now(),
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS cron_runs (
    id bigserial PRIMARY KEY,
    cron_id bigint,
    ran_at timestamptz DEFAULT now(),
    status text,
    error text
);
```

## Faults
F01 F02 F05 F06 F11 F12 F13
