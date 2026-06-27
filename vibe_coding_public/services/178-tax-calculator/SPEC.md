# 178-tax-calculator

**Lang**: Go 1.22 / gin
**Deps**: redis-cache, upstream (mock-upstream)
**Domain**: Commerce checkout — sales-tax rate lookup with cache.

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"tax-calculator"}`
- `POST /tax` body `{region, subtotal_cents}` →
  1. Redis `GET tax_rate:{region}` (2s timeout).
  2. On miss/error: `GET {UPSTREAM_URL}/tax_rate?region=X` → `{"rate_bp": int}` (2s timeout). Cache with `SET … EX 3600`.
  3. `tax = subtotal_cents * rate_bp / 10000`.
  4. Return `{region, rate_bp, tax_cents, total_cents}`.
- `GET /rates` — KEYS `tax_rate:*` then GET each, return map.
- `POST /rates/refresh?region=X` — DEL + force refetch upstream.
- `DELETE /rates/:region` — DEL key.

## Cross-cutting
- `redis.NewClient(&redis.Options{DialTimeout:2s, ReadTimeout:2s, WriteTimeout:2s})`.
- `http.Client{Timeout: 2*time.Second}`.
- `context.WithTimeout(ctx, 2*time.Second)` on every Redis op.
- `log.Printf("ERROR %s: %v", SERVICE, err)`.
- `gin.SetMode(gin.ReleaseMode); r := gin.New(); r.Use(gin.Recovery()); r.Run("0.0.0.0:8080")`.

## Env
- `REDIS_CACHE_HOST` / `REDIS_CACHE_PORT`
- `UPSTREAM_URL` (default `http://mock-upstream:8080`)
