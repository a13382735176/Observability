# 128-car-rental

Car rental management service. Persists rentals in Postgres with active/returned status tracking.

**Stack:** TypeScript / Express (node:20-alpine)
**Deps:** postgres

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"car-rental"}`
- `POST /rentals` — body `{user_id, vehicle_type, pickup_date, return_date, daily_rate_cents}` → inserts into `car_rentals`
- `GET /rentals/:user_id/active` — list active rentals for a user
- `PUT /rentals/:id/return` — mark rental returned
- `GET /rentals` — list all rentals (LIMIT 200)

## Schema
```sql
CREATE TABLE car_rentals(
  id serial PRIMARY KEY,
  user_id text,
  vehicle_type text,
  pickup_date date,
  return_date date,
  daily_rate_cents int,
  status text DEFAULT 'active',
  created_at timestamptz DEFAULT now()
);
```

All postgres errors logged at ERROR level prefixed `ERROR car-rental:`. 2-second connect / statement / query timeouts.
