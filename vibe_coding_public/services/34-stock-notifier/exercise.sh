exercise_once() {
  local base="$1"
  local sku="sku-$RANDOM"
  local user="u$RANDOM"

  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/healthz" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/subscribe" \
       -H 'content-type: application/json' \
       -d '{"user_id":"'"$user"'","sku":"'"$sku"'"}' 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' "$base/subscriptions/$sku" 2>&1
  curl -sS --max-time 3 -w 'HTTP_CODE:%{http_code}\n' -X POST "$base/notify" \
       -H 'content-type: application/json' \
       -d '{"sku":"'"$sku"'","qty_available":5}' 2>&1
}