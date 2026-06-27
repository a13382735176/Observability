# 167-terraform-state

Versioned Terraform state backend with per-workspace locks. Stores state JSON
blobs in Postgres (`state_versions`, jsonb payload) and a single active lock per
workspace (`state_locks`).

**Stack:** Python 3.12 / FastAPI 0.111 / Uvicorn 0.30 / psycopg[pool] 3.1
**Deps:** postgres

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"terraform-state"}`
- `POST /state/:workspace` — body is any JSON blob; persists as the next version
  (`max(version)+1`). Returns `{workspace, version, id, created_at}`.
- `GET /state/:workspace` — latest version's payload.
- `GET /state/:workspace/versions` — list of `{version, created_at}` (no payload).
- `GET /state/:workspace/version/:version` — specific version's payload.
- `POST /state/:workspace/lock` — body `{lock_id}` → inserts the lock row. Returns
  `409 Conflict` if a lock already exists.
- `DELETE /state/:workspace/lock/:lock_id` — deletes the matching lock; `404` if
  the workspace is not locked or the `lock_id` is wrong.

## Schema (auto-created at startup)
```sql
CREATE TABLE IF NOT EXISTS state_versions(
  id bigserial PRIMARY KEY,
  workspace text NOT NULL,
  version int NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz DEFAULT now(),
  UNIQUE(workspace, version)
);
CREATE TABLE IF NOT EXISTS state_locks(
  workspace text PRIMARY KEY,
  lock_id text NOT NULL,
  locked_at timestamptz DEFAULT now()
);
```

## Timeouts / logging
- `psycopg_pool.AsyncConnectionPool(min_size=1, max_size=4, timeout=2, kwargs={"connect_timeout":2})`.
- All errors logged as `log.error("terraform-state: ...: %s", e)`.
- Returns `503` on Postgres errors, `409` on lock conflict, `404` on missing.

## Faults
F01, F02, F05, F06, F11, F12, F13.
