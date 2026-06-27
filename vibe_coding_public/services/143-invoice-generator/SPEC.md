# 143-invoice-generator

C#/.NET 8 minimal-API service that issues invoices, persists header + lines in Postgres,
and emits stream events on `redis-stream` for invoice creation and payment.

## Stack
- ASP.NET Core 8 minimal API on `dotnet/sdk:8.0` → `dotnet/aspnet:8.0`
- Npgsql 8.0.4 (Postgres connection timeout = 2s)
- StackExchange.Redis 2.7.33 (ConnectTimeout = 2000ms, SyncTimeout = 2000ms)

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`)
- redis-stream (default port 6379)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"invoice-generator"}`
- `POST /invoices` — body `{customer_id, line_items:[{description, amount_cents, quantity}]}`
  computes `total = sum(amount * quantity)`, inserts header + lines, `XADD events:invoices`,
  returns the persisted invoice.
- `GET /invoices/:id` — returns invoice + lines
- `GET /invoices/customer/:customer_id` — last 20 invoices
- `PUT /invoices/:id/mark-paid` — sets `status='paid'`, `XADD events:invoice_paid`

## Schema (auto-created at startup)
```
invoices(id bigserial PK,
         customer_id text,
         total_cents bigint,
         status text default 'unpaid',
         issued_at timestamptz default now())

invoice_lines(id bigserial PK,
              invoice_id bigint,
              description text,
              amount_cents bigint,
              quantity int)
```

## Logging / timeouts
- All errors via `logger.LogError("invoice-generator: {Error}", e.Message)`.
- 2s timeouts on every Postgres and Redis op (connection string + Redis config + per-call timeout).

## Faults
F01, F02, F05, F06, F09, F10, F11, F12, F13.
