# 139-inventory-stock - upsert item and adjust stock.
exercise_once() {
  local base="$1"
  local sku="SKU-$RANDOM"
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/items" \
       -H 'content-type: application/json' \
       -d '{"sku":"'"$sku"'","name":"widget","quantity":25,"warehouse_id":"WH1"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/items/$sku" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/items/$sku/adjust" \
       -H 'content-type: application/json' \
       -d '{"delta":-1}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/items/low-stock" 2>&1
}
# 139-inventory-stock - upsert stock, adjust quantity, and read cache-backed APIs.
exercise_once() {
  local base="$1"
  local sku="SKU-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/items" \
       -H 'content-type: application/json' \
       -d '{"sku":"'"$sku"'","name":"Widget","quantity":25,"warehouse_id":"WH1"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/items/$sku" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/items/$sku/adjust" \
       -H 'content-type: application/json' \
       -d '{"delta":-3}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/items/low-stock" 2>&1
}