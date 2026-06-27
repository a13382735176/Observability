# 03-order-api (postgres + redis_stream) — POST a new order. The handler
# both INSERTs into postgres AND XADDs to redis-stream, exercising both deps.
exercise_once() {
  local base="$1"
  local resp id
  resp="$(curl -sS --max-time 4 -w '\nHTTP_CODE:%{http_code}' \
           -X POST "$base/orders" -H 'content-type: application/json' \
           -d '{"user_id":"u1","items":[{"sku":"sku-1","qty":1,"price_cents":100}]}' 2>&1)"
  echo "[create] $resp"
  id="$(printf '%s' "$resp" | grep -oE '"id":[0-9]+' | head -1 | grep -oE '[0-9]+')"
  if [[ -n "$id" ]]; then
    curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/$id" 2>&1
  fi
}
