# 177-cart-svc

**Lang**: Python 3.12 / FastAPI
**Deps**: redis-cache, postgres
**Domain**: Commerce checkout — shopping cart with checkout to orders.

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"cart-svc"}`
- `POST /cart/{user_id}/items` body `{sku, quantity, price_cents}` — HSET into `cart:{user_id}`, EXPIRE 86400.
- `GET /cart/{user_id}` — HGETALL items, sum totals.
- `DELETE /cart/{user_id}/items/{sku}` — HDEL.
- `DELETE /cart/{user_id}` — DEL key.
- `POST /cart/{user_id}/checkout` — read cart from Redis, insert into `orders` + `order_lines` in Postgres, DEL Redis key.

## Tables
- `orders(id BIGSERIAL PK, user_id TEXT, total_cents BIGINT, created_at TIMESTAMPTZ DEFAULT now())`
- `order_lines(id BIGSERIAL PK, order_id BIGINT, sku TEXT, quantity INT, price_cents INT)`

## Cross-cutting
- All Redis ops: `socket_connect_timeout=2, socket_timeout=2`.
- Postgres pool: `psycopg_pool.ConnectionPool(min=1, max=4, timeout=2, kwargs={"connect_timeout": 2})`.
- Tables created in FastAPI lifespan startup.
- Errors logged as `log.error("cart-svc: %s", e)`; map cache failures → 503.

## Env
- `PG_DSN` (default: `host=postgres port=5432 user=vibe password=vibe dbname=vibe`)
- `REDIS_CACHE_HOST` / `REDIS_CACHE_PORT`
