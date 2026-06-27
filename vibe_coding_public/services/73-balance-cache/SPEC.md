# 73-balance-cache

Financial balance cache (Go/gin, redis-cache).

## Deps
- redis-cache

## Endpoints
- GET /healthz
- GET /balance/:account_id
- PUT /balance/:account_id
- POST /invalidate/:account_id
