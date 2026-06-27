# 139-inventory-stock

Inventory stock keeper. Items live in Postgres (unique by `sku`); current per-SKU `quantity` is cached read-through in `redis-cache` as `stock:{sku}` with 10 min TTL.

**Stack:** Kotlin / Ktor (gradle:8.7-jdk21 → eclipse-temurin:21-jre-jammy)
**Deps:** postgres, redis-cache

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"inventory-stock"}`
- `POST /items` — body `{sku, name, quantity, warehouse_id}` — Postgres UPSERT on `sku`, then `SETEX stock:{sku} 600 quantity`
- `GET /items/:sku` — read-through cache; on miss SELECT and SETEX 600
- `POST /items/:sku/adjust` — body `{delta}` — `UPDATE quantity = quantity + delta WHERE sku=$1`, then `DEL stock:{sku}`
- `GET /items/low-stock` — `WHERE quantity < 10` (LIMIT 200)

## Schema
```sql
CREATE TABLE inventory_items(
  id bigserial PRIMARY KEY,
  sku text UNIQUE,
  name text,
  quantity int DEFAULT 0,
  warehouse_id text,
  updated_at timestamptz DEFAULT now()
);
```

All errors logged via SLF4J as `log.error("inventory-stock: {}", e.message, e)`. JDBC connect/socket timeout 2 s; Jedis pool timeout 2000 ms (max=4).
