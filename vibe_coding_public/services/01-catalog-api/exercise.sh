# 01-catalog-api (postgres) — GET /products + POST a new product.
exercise_once() {
  local base="$1"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/products" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/products/1" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/products" \
       -H 'content-type: application/json' \
       -d '{"name":"widget-'"$RANDOM"'","price_cents":199,"stock_qty":5}' 2>&1
}
