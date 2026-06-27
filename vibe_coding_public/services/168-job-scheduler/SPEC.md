# 168-job-scheduler

Go / gin service that schedules and dispatches background jobs.

## Dependencies
- postgres (table `scheduled_jobs`)
- redis-stream (`events:jobs`, `events:job_completed`)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"job-scheduler"}`
- `POST /jobs` body `{name, payload, run_at_iso}` → 201 with row
- `POST /jobs/run-due` → select pending jobs whose `run_at <= now()` (LIMIT 50),
  flip each to `dispatched`, XADD `events:jobs` (id, name); returns `{dispatched:N}`
- `GET /jobs/:id` → row or 404
- `GET /jobs?status=pending|dispatched|completed` → last 50 by id DESC
- `PUT /jobs/:id/complete` body `{result}` → mark completed, XADD `events:job_completed`

## Schema
```sql
CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id bigserial PRIMARY KEY,
    name text,
    payload jsonb DEFAULT '{}',
    run_at timestamptz,
    status text DEFAULT 'pending',
    result text,
    created_at timestamptz DEFAULT now(),
    completed_at timestamptz
);
```

## Faults
F01 F02 F05 F06 F09 F10 F11 F12 F13
