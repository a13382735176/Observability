# 182-package-tracking

Rust/Axum service tracking shipments through a chain of checkpoints, with redis caching of
the latest package state.

## Dependencies
- postgres (DB: `vibe`, user: `vibe`, password: `vibe`)
- redis-cache (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"package-tracking"}`
- `POST /packages` → body `{tracking_number, origin, destination, weight_kg}`; creates package row.
- `GET /packages/{tracking_number}` → package state; redis-cached for 300s.
- `POST /packages/{tracking_number}/checkpoint` → body `{location, status}`; appends checkpoint, updates package status, invalidates cache.
- `GET /packages/{tracking_number}/history` → ordered list of checkpoints.
- `GET /packages/active` → up to 100 packages whose current_status is not `delivered`.

## Schema
```
packages(id bigserial PK, tracking_number text unique, origin text, destination text,
         weight_kg double precision, current_status text default 'created',
         created_at timestamptz default now())
package_checkpoints(id bigserial PK, package_id bigint, location text, status text,
                    recorded_at timestamptz default now())
```

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
