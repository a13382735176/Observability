# access-proxy

Token-based authz cache. Rust/Axum + Redis-cache. Tokens auto-expire after 3600s.

## Endpoints
- `POST /tokens` body `{user_id, scopes:[str]}` → `{token, user_id, scopes, ttl}` (UUID; HSET token:{uuid}; EXPIRE 3600)
- `POST /validate` body `{token}` → `{valid:true,user_id,scopes}` or 401
- `DELETE /tokens/:token` → 204
