# 80-interest-calc

Financial interest/amortization calculator (C#/.NET8, postgres).

## Deps
- postgres

## Endpoints
- GET /healthz
- POST /calculate {principal_cents, annual_rate_pct, term_months}
- POST /rates {product_type, rate_pct}
- GET /rates

## Table
interest_rates(id serial, product_type text unique, rate_pct double precision, updated_at timestamptz)
