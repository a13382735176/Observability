exercise_once() {
  local base="$1"
  local bundle="starter-$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/bundles" \
       -H 'content-type: application/json' \
       -d '{"name":"'"$bundle"'","skus":["sku-1","sku-2"],"bundle_price_cents":1299}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/bundles" 2>&1
}