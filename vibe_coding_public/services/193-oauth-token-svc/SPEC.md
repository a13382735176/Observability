# 193-oauth-token-svc

OAuth2 client-credentials token issuer. Persists clients + issued tokens in Postgres and mirrors the active token → client_id mapping into `redis-cache` (key `token:{token}` EX 3600) for fast introspection.

**Stack:** TypeScript / Express (node:20-alpine)
**Deps:** postgres, redis-cache

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"oauth-token-svc"}`
- `POST /token` — body `{client_id, client_secret, grant_type}` → SELECT from `clients`, generate token, INSERT into `tokens`, SETEX cache → `{access_token, expires_in:3600, token_type:"Bearer"}`
- `POST /introspect` — body `{token}` → cache GET first, fall back to `SELECT … WHERE token=$1 AND expires_at > now()` → `{active, client_id?, expires_at?}`
- `POST /revoke` — body `{token}` → DELETE row + DEL cache key
- `POST /clients` — body `{client_id, client_secret}` → INSERT (upsert) row
- `GET /tokens/active` → `{active: <count where expires_at > now()>}`

## Schema
```sql
CREATE TABLE clients(
  id bigserial PRIMARY KEY,
  client_id text UNIQUE,
  client_secret text,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE tokens(
  id bigserial PRIMARY KEY,
  token text UNIQUE,
  client_id text,
  expires_at timestamptz,
  issued_at timestamptz DEFAULT now()
);
```

`pg.Pool` configured with `connectionTimeoutMillis: 2000`, `statement_timeout: 2000`, `query_timeout: 2000`. Redis ops are wrapped in a 2s `Promise.race` timeout. All failures logged at ERROR level prefixed `ERROR oauth-token-svc:`.
