# 196-api-key-vault

Rust/Axum service that issues opaque API keys (`vk_` + 32 hex chars), persists them in Postgres, and uses Redis as a 600s verification cache. Revoked keys are removed from cache and `verify` returns `{valid:false}`.

Endpoints: `GET /healthz`, `POST /keys`, `POST /verify`, `POST /keys/:id/revoke`, `GET /keys/owner/:owner_id` (no secret returned), `GET /keys` (active count).

Dependencies: postgres, redis-cache. Faults: F01, F02, F05, F06, F07, F08, F11, F12, F13.
