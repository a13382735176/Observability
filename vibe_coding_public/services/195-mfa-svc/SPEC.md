# 195-mfa-svc

Multi-factor authentication service. Persists per-user TOTP enrollments + verification audit + single-use backup codes in Postgres, caches a short-lived `mfa_verified:{user_id}` flag in `redis-cache` (EX 600).

**Stack:** Python 3.12 / FastAPI + uvicorn
**Deps:** postgres, redis-cache

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"mfa-svc"}`
- `POST /enroll` — body `{user_id}` → generate `secrets.token_hex(20)`, upsert `mfa_enrollments`, return `{secret, qr_url:"otpauth://totp/Vibe:<user_id>?secret=<secret>"}`
- `POST /verify` — body `{user_id, code}` → require 6-digit code, INSERT `mfa_verifications`, SET `mfa_verified:{user_id}` EX 600
- `GET /verified/{user_id}` — Redis GET `mfa_verified:{user_id}`
- `POST /backup-codes/{user_id}` — generate 10 hex(5) codes, INSERT each into `backup_codes`
- `POST /backup-codes/{user_id}/use` — body `{code}` → UPDATE used_at=now() WHERE user_id+code AND used_at IS NULL → `{used: bool}`

## Schema
```sql
CREATE TABLE mfa_enrollments(
  user_id TEXT PRIMARY KEY,
  secret TEXT NOT NULL,
  enrolled_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE mfa_verifications(
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  verified_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE backup_codes(
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  code TEXT NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

`psycopg_pool.AsyncConnectionPool` with `timeout=2`, `kwargs={"connect_timeout": 2}`. `redis.Redis(socket_connect_timeout=2, socket_timeout=2)`. All failures logged via `log.error("mfa-svc: %s", e)`.
