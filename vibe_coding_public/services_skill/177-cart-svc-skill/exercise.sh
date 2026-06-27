# 177-cart-svc - add cart item and execute checkout path.
exercise_once() {
  local base="$1"
  local user_id="user-$RANDOM"
  local sku="sku-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/cart/$user_id/items" \
       -H 'content-type: application/json' \
       -d '{"sku":"'"$sku"'","quantity":2,"price_cents":1299}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cart/$user_id" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/cart/$user_id/checkout" 2>&1
}
