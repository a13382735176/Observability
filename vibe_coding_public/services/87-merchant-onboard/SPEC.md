# 87-merchant-onboard

**Language**: Ruby/Sinatra  **Deps**: postgres

## Endpoints
- `GET  /healthz`
- `POST /merchants` body: `{name, email, business_type}` → create merchant
- `GET  /merchants/:id` → merchant by id
- `PUT  /merchants/:id/approve` → approve merchant
- `GET  /pending` → list pending merchants

## Table
`merchants(id serial PK, name text, email text UNIQUE, business_type text, status text DEFAULT 'pending', created_at timestamptz)`
