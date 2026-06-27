# 26-coupon-validator
Coupon code system storing coupons as Redis HASHes with usage tracking.
**Deps**: redis-cache  **Lang**: TypeScript/Express
**Endpoints**: GET /healthz, POST /validate, PUT /coupons/:code, GET /coupons
**Faults**: F01 F02 F07 F08 F11 F12 F13
