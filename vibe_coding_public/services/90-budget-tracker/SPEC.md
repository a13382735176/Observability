# 90-budget-tracker

**Language**: Python/aiohttp  **Deps**: postgres, redis-cache

## Endpoints
- `GET  /healthz`
- `POST /budgets` body: `{user_id, category, limit_cents, period}` → upsert budget
- `POST /expenses` body: `{user_id, category, amount_cents}` → DB insert + Redis INCR spent:{user_id}:{category}
- `GET  /budgets/:user_id/status` → compare Redis spent vs postgres limits

## Tables
`budgets(id serial PK, user_id text, category text, limit_cents bigint, period text, UNIQUE(user_id,category))`
`expenses(id serial PK, user_id text, category text, amount_cents bigint, ts timestamptz)`
