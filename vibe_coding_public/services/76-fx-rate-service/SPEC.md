# 76-fx-rate-service

Financial FX rates (TypeScript/Express).

## Deps
- redis-cache
- upstream (mock-upstream:8080)

## Endpoints
- GET /healthz
- GET /rates
- GET /rates/:pair
- POST /refresh
