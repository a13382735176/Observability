# 02-cart-service (redis_cache) — POST item to cart, GET cart.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' \
       -X POST "$base/cart/u1/items" -H 'content-type: application/json' \
       -d '{"sku":"sku-1","qty":1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/cart/u1" 2>&1
}
