# 179-promo-engine

Java / Spring Boot 3.3.0 (Java 21) service that manages promotional codes with a Redis
write-through cache backed by Postgres for persistence and a redemption ledger.

## Stack
- Spring Boot 3.3.0, `spring-boot-starter-web`, `spring-boot-starter-data-jpa`, `spring-boot-starter-data-redis`
- PostgreSQL JDBC (runtime)
- Built with `maven:3.9-eclipse-temurin-21`, runs on `eclipse-temurin:21-jre-jammy`

## Deps
- postgres (DB `vibe`, user `vibe`, password `vibe`) — schema auto-migrated via JPA `ddl-auto=update`
- redis-cache (default port 6379) — write-through cache `promo:<code>` with 600 s TTL

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"promo-engine"}`
- `POST /promos` — body `{code, discount_pct:int, valid_until_iso:string}` → INSERT into `promos`; warms cache `promo:<code>` for 600 s
- `POST /apply` — body `{code, subtotal_cents:long}` → Redis GET first; on miss falls back to `promos WHERE code=$1 AND active=true`; validates `valid_until > now()`; returns `{original_cents, discount_cents, final_cents}`
- `DELETE /promos/{code}` — soft-deletes (`active=false`) and evicts cache
- `GET /promos` — list all active promos
- `POST /promos/{code}/redeem` — body `{user_id}` → inserts into `promo_redemptions`

## Schema (auto-created via JPA)
```
promos(id bigserial PK,
       code text unique,
       discount_pct int,
       valid_until timestamptz,
       active boolean default true,
       created_at timestamptz default now())

promo_redemptions(id bigserial PK,
                  promo_code text,
                  user_id text,
                  redeemed_at timestamptz default now())
```

## Logging / timeouts
- All errors via `log.error("promo-engine: {}", e.getMessage(), e)`.
- Hikari `connection-timeout=2000`, Redis `timeout=2000` (2 s on both deps).

## Faults
F01, F02, F05, F06, F07, F08, F11, F12, F13.
