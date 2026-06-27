# 88-split-pay

**Language**: Rust/Actix-web  **Deps**: postgres, redis-cache

## Endpoints
- `GET  /healthz`
- `POST /split` body: `{payer_id, participants:[{user_id,amount_cents}], description}` → DB splits+items + Redis cache
- `GET  /splits/:id` → split with items
- `GET  /splits/user/:user_id` → user's split items

## Tables
`splits(id serial PK, payer_id text, total_cents bigint, description text, status text DEFAULT 'open', created_at timestamptz)`
`split_items(id serial PK, split_id int, user_id text, amount_cents bigint, settled bool DEFAULT false)`
