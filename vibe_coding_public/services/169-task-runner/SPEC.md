# 169-task-runner

Spring Boot 3.3.0 / Java 21 service that tracks and dispatches task work units.

## Dependencies
- postgres (table `tasks`)
- redis-stream (`events:tasks`, `events:task_started`, `events:task_finished`)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"task-runner"}`
- `POST /tasks` body `{type, parameters}` → 201; XADD `events:tasks` (id, type)
- `GET /tasks/:id` → row or 404
- `POST /tasks/:id/start` → mark `running`, set `started_at`; XADD `events:task_started`
- `POST /tasks/:id/finish` body `{output, success}` → mark `success` or `failed`,
  set `finished_at`, `output`; XADD `events:task_finished` (id, status)
- `GET /tasks?status=...&limit=50` → last N by id DESC

## Schema
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id bigserial PRIMARY KEY,
    type text,
    parameters text DEFAULT '{}',
    status text DEFAULT 'queued',
    started_at timestamptz,
    finished_at timestamptz,
    output text,
    created_at timestamptz DEFAULT now()
);
```
(Hibernate `ddl-auto=update` creates / migrates this.)

## Faults
F01 F02 F05 F06 F09 F10 F11 F12 F13
