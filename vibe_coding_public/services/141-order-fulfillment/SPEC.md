# 141-order-fulfillment

Order fulfillment service. Persists orders + line items in Postgres and emits domain events to `redis-stream` (`events:orders`, `events:order_status`).

**Stack:** Python / FastAPI (python:3.12-slim)
**Deps:** postgres, redis-stream

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"order-fulfillment"}`
- `POST /orders` — body `{user_id, items:[{sku, quantity, price_cents}]}`. Computes `total_cents = sum(quantity * price_cents)`, INSERTs into `orders` + `order_items` in one connection (transactional commit), then `XADD events:orders {order_id, user_id, total_cents}`.
- `GET /orders/:id` — returns order header + all line items via `LEFT JOIN`.
- `GET /orders/user/:user_id` — last 20 orders by `id DESC`.
- `PUT /orders/:id/status` — body `{status}` — `UPDATE orders SET status=$1`, then `XADD events:order_status {order_id, status}`.

## Schema
```sql
CREATE TABLE orders(
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  total_cents BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'placed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE order_items(
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT NOT NULL,
  sku TEXT NOT NULL,
  quantity INT NOT NULL,
  price_cents INT NOT NULL
);
```

All errors logged via `log.error("order-fulfillment: %s", e)`. `psycopg_pool.AsyncConnectionPool` with `timeout=2` and `kwargs={"connect_timeout": 2}`; `redis.Redis` (sync) with `socket_connect_timeout=2, socket_timeout=2`.
