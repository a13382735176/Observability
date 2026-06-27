# 166-deployment-tracker

C#/.NET 8 minimal-API service that records service deployments per environment in
Postgres and emits `events:deployments` / `events:rollbacks` on Redis Streams.

## Stack
- ASP.NET Core 8 minimal API on `dotnet/sdk:8.0` → `dotnet/aspnet:8.0`
- Npgsql 8.0.4 (Postgres `Timeout=2;Command Timeout=2`)
- StackExchange.Redis 2.7.33 (`ConnectTimeout=2000`, `SyncTimeout=2000`)

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"deployment-tracker"}`
- `POST /deployments` — body `{service, version, environment, deployed_by}` →
  inserts a row, `XADD events:deployments`, returns the persisted deployment.
- `GET /deployments/:service` — last 20 deployments for a service.
- `GET /deployments/active/:environment` — latest deployment per service in an
  environment via `SELECT DISTINCT ON (service) ... ORDER BY service, id DESC`.
- `PUT /deployments/:id/rollback` — body `{previous_version}` → inserts a new row
  with `rollback=true`, `XADD events:rollbacks`.
- `GET /deployments` — last 50 across all services.

## Schema (auto-created at startup)
```sql
CREATE TABLE IF NOT EXISTS deployments (
  id bigserial PRIMARY KEY,
  service text NOT NULL,
  version text NOT NULL,
  environment text NOT NULL,
  deployed_by text,
  rollback boolean DEFAULT false,
  deployed_at timestamptz DEFAULT now()
);
```

## Logging / timeouts
- `logger.LogError("deployment-tracker: {Error}", e.Message)` on every catch.
- 2 s timeouts on every Postgres and Redis op (connection string + Redis config).

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
