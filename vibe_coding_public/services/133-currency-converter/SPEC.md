# 133-currency-converter

Go/gin service that converts currency by fetching live rates from `mock-upstream`
and caching them in redis for 60 seconds.

## Dependencies
- redis-cache (default port 6379)
- upstream `mock-upstream:8080` (returns `{"rate":1.08}` on `GET /rates?pair=USDEUR`)

## Endpoints
- `GET /healthz` → `{"status":"ok","service":"currency-converter"}`
- `GET /convert?from=USD&to=EUR&amount=100` → `{result: amount*rate, rate, ...}`.
- `POST /rates/refresh` → preload USDEUR, USDJPY, EURGBP into the rates hash.
- `GET /rates` → `HGETALL rates`.

## Caching
- Redis key: hash `rates`, field `{from}_{to}`, TTL 60s on the hash key.

## Faults
F01, F02, F03, F04, F07, F08, F11, F12, F13.
