# 141-order-fulfillment - create order and update order status.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/orders" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","items":[{"sku":"SKU-1","quantity":1,"price_cents":1999}]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/user/$user" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/orders/1/status" \
       -H 'content-type: application/json' \
       -d '{"status":"processing"}' 2>&1
}
# 141-order-fulfillment - create orders and update status while probing health.
exercise_once() {
  local base="$1"
  local user="user-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/orders" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","items":[{"sku":"SKU-1","quantity":1,"price_cents":1999}]}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/orders/1/status" \
       -H 'content-type: application/json' \
       -d '{"status":"shipped"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/orders/user/$user" 2>&1
}