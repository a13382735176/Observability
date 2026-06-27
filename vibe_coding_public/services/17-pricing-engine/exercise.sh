# 17-pricing-engine - update SKU price and query price views.
exercise_once() {
  local base="$1"
  local sku="sku-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X PUT "$base/price/$sku" \
       -H 'content-type: application/json' \
       -d '{"price":1299}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/price/$sku" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/prices" 2>&1
}
