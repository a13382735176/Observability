# 144-chargeback-svc

Go / chi service for payment chargebacks. Persists chargebacks in Postgres and emits
stream events on `redis-stream` on creation and resolution.

## Stack
- Go 1.22 / `github.com/go-chi/chi/v5` v5.0.12
- `github.com/jackc/pgx/v5` v5.6.0 with a `pgxpool.Pool` and `ConnectTimeout = 2s`
- `github.com/redis/go-redis/v9` v9.5.1 with 2s dial/read/write timeouts

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"chargeback-svc"}`
- `POST /chargebacks` — body `{payment_id, reason, amount_cents}` →
  `INSERT INTO chargebacks ...`; `XADD events:chargebacks {id, payment_id, amount_cents}`.
- `GET /chargebacks/:payment_id` — all chargebacks for a payment.
- `PUT /chargebacks/:id/resolve` — body `{resolution}` →
  `UPDATE ... SET status='resolved', resolution=...`; `XADD events:chargeback_resolved`.
- `GET /chargebacks/pending` — all rows `WHERE status='pending'`.

## Schema (auto-created at startup)
```
chargebacks(id bigserial PK,
            payment_id int,
            reason text,
            amount_cents int,
            status text default 'pending',
            resolution text,
            created_at timestamptz default now(),
            resolved_at timestamptz)
```

## Logging / timeouts
- All errors via `log.Printf("ERROR chargeback-svc: %v", err)`.
- 2s timeouts on every Postgres and Redis op.

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
