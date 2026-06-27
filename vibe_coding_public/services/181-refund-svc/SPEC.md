# 181-refund-svc

C# / .NET 8 minimal-API refund service. Persists refunds in Postgres and emits
stream events to `redis-stream` for refund request, approval, and denial.

## Stack
- ASP.NET Core 8 minimal API on `dotnet/sdk:8.0` → `dotnet/aspnet:8.0`
- Npgsql 8.0.4 (Postgres connection timeout = 2 s)
- StackExchange.Redis 2.7.33 (ConnectTimeout = 2000 ms, SyncTimeout = 2000 ms)

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"refund-svc"}`
- `POST /refunds` — body `{order_id, amount_cents, reason}` → INSERT (status=`pending`), `XADD events:refunds`
- `GET /refunds/:id` — returns refund row
- `GET /refunds/order/:order_id` — list refunds for an order
- `PUT /refunds/:id/approve` — sets `status='approved'`, `approved_at=now()`, `XADD events:refund_approved`
- `PUT /refunds/:id/deny` — body `{denial_reason}` → sets `status='denied'`, `denial_reason`, `XADD events:refund_denied`

## Schema (auto-created at startup)
```
refunds(id bigserial PK,
        order_id bigint,
        amount_cents bigint,
        reason text,
        status text default 'pending',
        denial_reason text,
        requested_at timestamptz default now(),
        approved_at timestamptz)
```

## Logging / timeouts
- All errors via `logger.LogError("refund-svc: {Error}", e.Message)`.
- 2 s timeouts on every Postgres and Redis op (connection string + Redis config).

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
