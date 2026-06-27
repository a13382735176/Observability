# 81-tax-reporting

**Language**: Python/Flask  **Deps**: postgres

## Endpoints
- `GET  /healthz` → `{"status":"ok","service":"tax-reporting"}`
- `POST /reports` body: `{user_id, tax_year, income_cents, deductions_cents}` → taxable=income-deductions; saves to DB
- `GET  /reports/:user_id` → list all reports for user
- `GET  /report/:id` → single report by id

## Table
`tax_reports(id serial PK, user_id text, tax_year int, income_cents bigint, deductions_cents bigint, taxable_cents bigint, created_at timestamptz)`
